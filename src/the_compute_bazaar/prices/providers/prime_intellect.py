"""Prime Intellect live GPU availability adapter."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests

from ..normalize import canonical_gpu_model
from ..schemas import GpuOffer


DEFAULT_PRIME_INTELLECT_API_BASE = "https://api.primeintellect.ai/api/v1"
PRIME_FRONTIER_GPU_TYPES = ("H100_80GB", "H200_141GB", "B200_180GB", "B300_262GB")
PROVIDER_ALIASES = {
    "lambda_labs": "lambda",
    "lambdalabs": "lambda",
    "massed_compute": "massed_compute",
    "massedcompute": "massed_compute",
}


@dataclass(frozen=True)
class PrimeAvailabilityFetch:
    raw_payload: dict[str, Any]
    items: list[dict[str, Any]]


class PrimeIntellectClient:
    def __init__(
        self,
        *,
        api_key: str,
        api_base: str = DEFAULT_PRIME_INTELLECT_API_BASE,
        session: requests.Session | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("Prime Intellect API key is required")
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.session = session or requests.Session()

    def fetch_frontier_availability(
        self,
        *,
        gpu_types: Sequence[str] = PRIME_FRONTIER_GPU_TYPES,
        max_pages_per_gpu: int = 20,
    ) -> PrimeAvailabilityFetch:
        segments: list[dict[str, Any]] = []
        items: list[dict[str, Any]] = []
        seen: set[str] = set()

        for gpu_type in gpu_types:
            for page in range(1, max(1, max_pages_per_gpu) + 1):
                query = {"gpu_type": gpu_type, "page": page, "page_size": 100}
                response = self.session.get(
                    f"{self.api_base}/availability/gpus",
                    params=query,
                    headers={
                        "Accept": "application/json",
                        "Authorization": f"Bearer {self.api_key}",
                    },
                    timeout=60,
                )
                response.raise_for_status()
                payload = response.json()
                page_items = _extract_items(payload)
                segments.append(
                    {
                        "gpu_type": gpu_type,
                        "page": page,
                        "query": query,
                        "payload": payload,
                        "extracted_offer_count": len(page_items),
                    }
                )
                for item in page_items:
                    key = _availability_key(item)
                    if key not in seen:
                        seen.add(key)
                        items.append(item)

                total_count = (
                    _int_or_none(payload.get("totalCount"))
                    if isinstance(payload, Mapping)
                    else None
                )
                if (
                    not page_items
                    or len(page_items) < 100
                    or (total_count is not None and page * 100 >= total_count)
                ):
                    break

        return PrimeAvailabilityFetch(
            raw_payload={
                "mode": "frontier_gpu_availability",
                "gpu_types": list(gpu_types),
                "segments": segments,
                "offer_count": len(items),
                "items": items,
            },
            items=items,
        )


def normalize_availability(
    items: Iterable[Mapping[str, Any]],
    *,
    observed_at: datetime,
    raw_ref: str | None,
) -> tuple[list[GpuOffer], list[str]]:
    normalized: list[GpuOffer] = []
    unknown_gpu_names: list[str] = []

    for entry in items:
        gpu_name = str(entry.get("gpuType") or "")
        gpu_memory_gb = _float_or_none(entry.get("gpuMemory"))
        gpu_model = canonical_gpu_model(
            gpu_name, gpu_memory_gb * 1024 if gpu_memory_gb else None
        )
        if not gpu_model:
            if gpu_name:
                unknown_gpu_names.append(gpu_name)
            continue

        gpu_count = _int_or_none(entry.get("gpuCount")) or 1
        prices = entry.get("prices") if isinstance(entry.get("prices"), Mapping) else {}
        price = _float_or_none(prices.get("onDemand"))
        if price is None or price <= 0:
            continue
        if gpu_count > 1:
            gpu_model = f"{gpu_model}_x{gpu_count}"

        stock_status = str(entry.get("stockStatus") or "").strip()
        is_available = stock_status.lower() not in {"", "none", "unavailable"}
        is_spot = _bool_or_none(entry.get("isSpot"))
        if is_spot:
            availability_status = (
                "spot_available" if is_available else "spot_unavailable"
            )
        else:
            availability_status = "available" if is_available else "unavailable"
        provider_name = str(entry.get("provider") or "")
        provider = _provider_id(provider_name)
        cloud_id = str(entry.get("cloudId") or "")
        data_center = str(entry.get("dataCenter") or "")
        country = _string_or_none(entry.get("country"))
        region = (
            ", ".join(
                part
                for part in (_string_or_none(entry.get("region")), data_center or None)
                if part
            )
            or None
        )

        normalized.append(
            GpuOffer(
                provider=provider,
                source_connector="prime_intellect",
                source_offer_id=":".join(
                    part
                    for part in (provider_name, cloud_id, data_center, str(gpu_count))
                    if part
                ),
                observed_at=observed_at,
                gpu_raw_name=gpu_name,
                gpu_model=gpu_model,
                gpu_count=gpu_count,
                vram_gb=gpu_memory_gb,
                price_usd_hr=price,
                available_gpu_count=gpu_count if is_available else None,
                currency=str(prices.get("currency") or "USD"),
                country=country,
                region=region,
                is_spot=is_spot,
                is_secure=str(entry.get("security") or "").lower() == "secure_cloud",
                availability_status=availability_status,
                raw_ref=raw_ref,
                metadata={
                    "upstream_provider": provider_name,
                    "cloud_id": cloud_id,
                    "data_center": data_center,
                    "socket": entry.get("socket"),
                    "stock_status": stock_status,
                    "security": entry.get("security"),
                    "community_price": prices.get("communityPrice"),
                    "is_variable_price": prices.get("isVariable"),
                    "capacity_basis": "available_bundle_lower_bound",
                },
            )
        )

    return normalized, sorted(set(unknown_gpu_names))


def _extract_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, Mapping) and isinstance(payload.get("items"), list):
        return [dict(row) for row in payload["items"] if isinstance(row, Mapping)]
    return []


def _availability_key(entry: Mapping[str, Any]) -> str:
    return ":".join(
        str(entry.get(key) or "")
        for key in (
            "provider",
            "cloudId",
            "gpuType",
            "gpuCount",
            "region",
            "dataCenter",
            "security",
        )
    )


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _bool_or_none(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes"}


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _provider_id(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    return PROVIDER_ALIASES.get(normalized, normalized) or "prime_intellect"
