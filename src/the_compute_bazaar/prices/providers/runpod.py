"""RunPod live GPU type pricing and stock adapter."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
import hashlib
from typing import Any

import requests

from ..normalize import canonical_gpu_model
from ..events import sha256_json
from ..schemas import OfferObservation


DEFAULT_RUNPOD_GRAPHQL_URL = "https://api.runpod.io/graphql"
RUNPOD_GPU_TYPES_QUERY = """
query GpuTypes {
  gpuTypes {
    id
    displayName
    memoryInGb
    secureCloud
    communityCloud
    lowestPrice(input: {gpuCount: 1}) {
      stockStatus
      uninterruptablePrice
      availableGpuCounts
    }
  }
}
"""
RUNPOD_LIVE_MARKET_QUERY = """
query LiveGpuMarket {
  gpuTypes {
    id
    displayName
    memoryInGb
    secureCloud
    communityCloud
    securePrice
    communityPrice
  }
  dataCenters {
    id
    name
    location
    gpuAvailability {
      gpuTypeId
      displayName
      stockStatus
    }
  }
}
"""


@dataclass(frozen=True)
class RunpodGpuTypesFetch:
    raw_payload: dict[str, Any]
    gpu_types: list[dict[str, Any]]


@dataclass(frozen=True)
class RunpodLiveMarketFetch:
    raw_payload: dict[str, Any]
    gpu_types: list[dict[str, Any]]
    data_centers: list[dict[str, Any]]


class RunpodClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        graphql_url: str = DEFAULT_RUNPOD_GRAPHQL_URL,
        session: requests.Session | None = None,
    ) -> None:
        self.api_key = api_key
        self.graphql_url = graphql_url
        self.session = session or requests.Session()

    def fetch_gpu_types(self) -> RunpodGpuTypesFetch:
        payload = self._query(RUNPOD_GPU_TYPES_QUERY)
        gpu_types = _extract_rows(payload, "gpuTypes")
        return RunpodGpuTypesFetch(
            raw_payload={
                "query": RUNPOD_GPU_TYPES_QUERY,
                "payload": payload,
                "gpu_type_count": len(gpu_types),
                "gpu_types": gpu_types,
            },
            gpu_types=gpu_types,
        )

    def fetch_live_market(self) -> RunpodLiveMarketFetch:
        payload = self._query(RUNPOD_LIVE_MARKET_QUERY)
        gpu_types = _extract_rows(payload, "gpuTypes")
        data_centers = _extract_rows(payload, "dataCenters")
        return RunpodLiveMarketFetch(
            raw_payload={
                "query": RUNPOD_LIVE_MARKET_QUERY,
                "payload": payload,
                "gpu_type_count": len(gpu_types),
                "data_center_count": len(data_centers),
            },
            gpu_types=gpu_types,
            data_centers=data_centers,
        )

    def _query(self, query: str) -> dict[str, Any]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            response = self.session.post(
                self.graphql_url,
                json={"query": query},
                headers=headers,
                timeout=60,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError("RunPod API request failed") from exc
        payload = response.json()
        if isinstance(payload, Mapping) and payload.get("errors"):
            raise RuntimeError(f"RunPod GraphQL returned errors: {payload['errors']}")
        if not isinstance(payload, dict):
            raise RuntimeError("RunPod GraphQL returned a non-object response")
        return payload


def normalize_gpu_types(
    gpu_types: Iterable[Mapping[str, Any]],
    *,
    observed_at: datetime,
    raw_ref: str | None,
) -> tuple[list[OfferObservation], list[str]]:
    normalized: list[OfferObservation] = []
    unknown_gpu_names: list[str] = []

    for entry in gpu_types:
        gpu_name = str(entry.get("displayName") or entry.get("id") or "")
        vram_gb = _float_or_none(entry.get("memoryInGb"))
        gpu_model = canonical_gpu_model(gpu_name, vram_gb * 1024 if vram_gb else None)
        if not gpu_model:
            if gpu_name:
                unknown_gpu_names.append(gpu_name)
            continue

        lowest_price = (
            entry.get("lowestPrice")
            if isinstance(entry.get("lowestPrice"), Mapping)
            else {}
        )
        price = _float_or_none(lowest_price.get("uninterruptablePrice"))
        if price is None or price <= 0:
            continue
        stock_status = str(lowest_price.get("stockStatus") or "")
        availability_status = (
            "available" if stock_status.lower() not in {"", "none"} else "unavailable"
        )

        normalized.append(
            OfferObservation(
                provider="runpod",
                source_offer_id=f"{entry.get('id')}:ondemand:1",
                observed_at=observed_at,
                gpu_raw_name=gpu_name,
                gpu_model=gpu_model,
                gpu_count=1,
                vram_gb=vram_gb,
                price_usd_instance_hr=price,
                available_gpu_count=1 if availability_status == "available" else None,
                country=None,
                region="global",
                is_spot=False,
                is_secure=_bool_or_none(entry.get("secureCloud")),
                availability_status=availability_status,
                raw_ref=raw_ref,
                metadata={
                    "gpu_type_id": entry.get("id"),
                    "stock_status": stock_status,
                    "available_gpu_counts": lowest_price.get("availableGpuCounts"),
                    "community_cloud": entry.get("communityCloud"),
                    "price_basis": "runpod_uninterruptable_gpu_hour",
                    "capacity_basis": "available_gpu_type_lower_bound",
                },
            )
        )

    return normalized, sorted(set(unknown_gpu_names))


def normalize_live_market(
    gpu_types: Iterable[Mapping[str, Any]],
    data_centers: Iterable[Mapping[str, Any]],
    *,
    observed_at: datetime,
    batch_id: str,
    purpose: str,
    query_scope: dict[str, Any],
) -> list[OfferObservation]:
    gpu_types = list(gpu_types)
    data_centers = list(data_centers)
    raw_hash = sha256_json({"gpu_types": gpu_types, "data_centers": data_centers})
    locations = _live_locations(data_centers)
    observations: list[OfferObservation] = []
    for row in gpu_types:
        native_gpu_id = str(row.get("id") or "")
        gpu_name = str(row.get("displayName") or native_gpu_id)
        vram_gb = _float_or_none(row.get("memoryInGb"))
        gpu_model = canonical_gpu_model(
            gpu_name, vram_gb * 1024 if vram_gb is not None else None
        )
        if not native_gpu_id or not gpu_model:
            continue
        available_locations = locations.get(native_gpu_id, ())
        for cloud_type, enabled_key, price_key in (
            ("secure", "secureCloud", "securePrice"),
            ("community", "communityCloud", "communityPrice"),
        ):
            price = _float_or_none(row.get(price_key))
            if not row.get(enabled_key) or price is None or price <= 0:
                continue
            location_ids = tuple(item[0] for item in available_locations)
            stock = _best_stock(item[2] for item in available_locations)
            native_offer_id = f"{native_gpu_id}:{cloud_type}"
            offer_id = _offer_id("runpod", native_offer_id)
            observations.append(
                OfferObservation(
                    provider="runpod",
                    source_offer_id=offer_id,
                    observed_at=observed_at,
                    gpu_raw_name=gpu_name,
                    gpu_model=gpu_model,
                    gpu_count=1,
                    vram_gb=vram_gb,
                    price_usd_instance_hr=price,
                    source_connector="runpod",
                    is_secure=cloud_type == "secure",
                    availability_status=(
                        "available" if location_ids else "unavailable"
                    ),
                    stock_status=stock,
                    price_basis="provider_live_price",
                    metadata={"native_offer_id": native_offer_id},
                    observation_id=f"{batch_id}:{offer_id}",
                    batch_id=batch_id,
                    observation_purpose=purpose,
                    observation_resolution="deployment_option",
                    selection_resolution="datacenter_set",
                    query_scope=query_scope,
                    cloud_type=cloud_type,
                    location_ids=location_ids,
                    selection_fingerprint=(f"runpod:{native_gpu_id}:{cloud_type}:1"),
                    native_selection={
                        "provider": "runpod",
                        "operation": "create_pod",
                        "gpuTypeIds": [native_gpu_id],
                        "gpuCount": 1,
                        "cloudType": cloud_type.upper(),
                        "dataCenterIds": list(location_ids),
                    },
                    raw_hash=raw_hash,
                    methodology_version="runpod_live_market",
                )
            )
    return observations


def _extract_gpu_types(payload: Any) -> list[dict[str, Any]]:
    return _extract_rows(payload, "gpuTypes")


def _extract_rows(payload: Any, field: str) -> list[dict[str, Any]]:
    if not isinstance(payload, Mapping):
        return []
    data = payload.get("data")
    if not isinstance(data, Mapping) or not isinstance(data.get(field), list):
        return []
    return [dict(row) for row in data[field] if isinstance(row, Mapping)]


def _live_locations(
    data_centers: Iterable[Mapping[str, Any]],
) -> dict[str, tuple[tuple[str, str, str], ...]]:
    result: dict[str, list[tuple[str, str, str]]] = {}
    for center in data_centers:
        center_id = str(center.get("id") or "")
        availability = center.get("gpuAvailability")
        if not center_id or not isinstance(availability, list):
            continue
        name = str(center.get("name") or center.get("location") or center_id)
        for row in availability:
            if not isinstance(row, Mapping):
                continue
            gpu_type_id = str(row.get("gpuTypeId") or "")
            stock = str(row.get("stockStatus") or "none")
            if gpu_type_id and _stock_rank(stock):
                result.setdefault(gpu_type_id, []).append((center_id, name, stock))
    return {
        key: tuple(sorted(values, key=lambda item: item[0]))
        for key, values in result.items()
    }


def _best_stock(values: Iterable[str]) -> str:
    return max(values, key=_stock_rank, default="none")


def _stock_rank(value: str) -> int:
    return {"high": 3, "medium": 2, "low": 1}.get(value.strip().lower(), 0)


def _offer_id(provider: str, native_offer_id: str) -> str:
    digest = hashlib.sha256(native_offer_id.encode()).hexdigest()[:12]
    return f"{provider}:{digest}"


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bool_or_none(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes"}
