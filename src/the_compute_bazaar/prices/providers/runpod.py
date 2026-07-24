"""RunPod live GPU type pricing and stock adapter."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests

from ..normalize import canonical_gpu_model
from ..schemas import GpuOffer


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


@dataclass(frozen=True)
class RunpodGpuTypesFetch:
    raw_payload: dict[str, Any]
    gpu_types: list[dict[str, Any]]


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
        request_kwargs: dict[str, Any] = {}
        if self.api_key:
            request_kwargs["params"] = {"api_key": self.api_key}
        response = self.session.post(
            self.graphql_url,
            json={"query": RUNPOD_GPU_TYPES_QUERY},
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            timeout=60,
            **request_kwargs,
        )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, Mapping) and payload.get("errors"):
            raise RuntimeError(f"RunPod GraphQL returned errors: {payload['errors']}")
        gpu_types = _extract_gpu_types(payload)
        return RunpodGpuTypesFetch(
            raw_payload={
                "query": RUNPOD_GPU_TYPES_QUERY,
                "payload": payload,
                "gpu_type_count": len(gpu_types),
                "gpu_types": gpu_types,
            },
            gpu_types=gpu_types,
        )


def normalize_gpu_types(
    gpu_types: Iterable[Mapping[str, Any]],
    *,
    observed_at: datetime,
    raw_ref: str | None,
) -> tuple[list[GpuOffer], list[str]]:
    normalized: list[GpuOffer] = []
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
            GpuOffer(
                provider="runpod",
                source_offer_id=f"{entry.get('id')}:ondemand:1",
                observed_at=observed_at,
                gpu_raw_name=gpu_name,
                gpu_model=gpu_model,
                gpu_count=1,
                vram_gb=vram_gb,
                price_usd_hr=price,
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


def _extract_gpu_types(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, Mapping):
        return []
    data = payload.get("data")
    if not isinstance(data, Mapping) or not isinstance(data.get("gpuTypes"), list):
        return []
    return [dict(row) for row in data["gpuTypes"] if isinstance(row, Mapping)]


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
