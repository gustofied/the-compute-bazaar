"""GetDeploying authenticated external GPU offering adapter."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests

from ..normalize import canonical_gpu_model
from ..schemas import GpuOffer
from .http import retrying_session


DEFAULT_GETDEPLOYING_API_URL = "https://getdeploying.com/api/gpu-offerings"
DEFAULT_FRONTIER_GPU_SLUGS = (
    "nvidia-h100",
    "nvidia-h200",
    "nvidia-b200",
    "nvidia-b300",
)
GPU_NAMES_BY_SLUG = {
    "nvidia-h100": "NVIDIA H100",
    "nvidia-h200": "NVIDIA H200",
    "nvidia-b200": "NVIDIA B200",
    "nvidia-b300": "NVIDIA B300",
}
FRONTIER_VRAM_GB = {
    "nvidia-h100": 80.0,
    "nvidia-h200": 141.0,
    "nvidia-b200": 180.0,
    "nvidia-b300": 288.0,
}


@dataclass(frozen=True)
class GetDeployingFetch:
    raw_payload: dict[str, Any]
    offerings: list[dict[str, Any]]


class GetDeployingClient:
    def __init__(
        self,
        *,
        api_key: str,
        api_url: str = DEFAULT_GETDEPLOYING_API_URL,
        session: requests.Session | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("GetDeploying API key is required")
        self.api_key = api_key
        self.api_url = api_url
        self.session = session or retrying_session()

    def fetch_frontier_offerings(
        self,
        *,
        gpu_slugs: Sequence[str] = DEFAULT_FRONTIER_GPU_SLUGS,
        page_size: int = 100,
        max_pages: int = 20,
    ) -> GetDeployingFetch:
        effective_page_size = max(1, min(int(page_size), 100))
        pages: list[dict[str, Any]] = []
        offerings: list[dict[str, Any]] = []
        for page in range(1, max(1, int(max_pages)) + 1):
            query = {
                "gpu_model": ",".join(gpu_slugs),
                "page": page,
                "page_size": effective_page_size,
                "sort": "price_per_gpu_hour",
            }
            response = self.session.get(
                self.api_url,
                params=query,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                    "User-Agent": "the-compute-bazaar/0.1",
                },
                timeout=60,
            )
            response.raise_for_status()
            payload = response.json()
            rows = _extract_offerings(payload)
            offerings.extend(rows)
            pages.append(
                {
                    "page": page,
                    "query": query,
                    "payload": payload,
                    "item_count": len(rows),
                }
            )
            page_count = (
                _int_or_none(payload.get("page_count"))
                if isinstance(payload, Mapping)
                else None
            )
            if (
                not rows
                or len(rows) < effective_page_size
                or (page_count is not None and page >= page_count)
            ):
                break

        return GetDeployingFetch(
            raw_payload={
                "mode": "authenticated_external_frontier_gpu_offerings",
                "source_url": self.api_url,
                "gpu_slugs": list(gpu_slugs),
                "page_size": effective_page_size,
                "page_count": len(pages),
                "item_count": len(offerings),
                "pages": pages,
            },
            offerings=offerings,
        )


def normalize_external_offerings(
    offerings: Iterable[Mapping[str, Any]],
    *,
    fetched_at: datetime,
    raw_ref: str | None,
) -> tuple[list[GpuOffer], list[str]]:
    normalized: list[GpuOffer] = []
    unknown_gpu_names: list[str] = []

    for entry in offerings:
        provider_data = _mapping(entry.get("provider"))
        configuration = _mapping(entry.get("configuration"))
        pricing = _mapping(entry.get("pricing"))
        status = _mapping(entry.get("status"))
        provider = str(provider_data.get("id") or "").strip().lower()
        source_offer_id = str(entry.get("id") or "").strip()
        gpu_slug = str(configuration.get("gpu_model") or "").strip().lower()
        gpu_name = GPU_NAMES_BY_SLUG.get(gpu_slug, gpu_slug)
        gpu_count = _int_or_none(configuration.get("gpu_count")) or 1
        source_vram_gb = _float_or_none(configuration.get("vram_per_gpu_gb"))
        vram_gb = FRONTIER_VRAM_GB.get(gpu_slug) or source_vram_gb
        hourly_price = _float_or_none(pricing.get("hourly"))
        if (
            not provider
            or not source_offer_id
            or not gpu_name
            or gpu_count <= 0
            or vram_gb is None
            or hourly_price is None
            or hourly_price <= 0
        ):
            continue

        gpu_model = canonical_gpu_model(gpu_name, vram_gb * 1024)
        if not gpu_model:
            unknown_gpu_names.append(gpu_name)
            continue
        if gpu_count > 1:
            gpu_model = f"{gpu_model}_x{gpu_count}"

        billing_type = str(pricing.get("billing_type") or "").strip().lower()
        observed_at = _parse_datetime(status.get("last_verified")) or fetched_at
        normalized.append(
            GpuOffer(
                provider=provider,
                source_connector="getdeploying",
                source_offer_id=f"getdeploying:{source_offer_id}",
                observed_at=observed_at,
                gpu_raw_name=gpu_name,
                gpu_model=gpu_model,
                gpu_count=gpu_count,
                vram_gb=vram_gb,
                price_usd_hr=hourly_price,
                currency=str(pricing.get("currency") or "USD"),
                country=_string_or_none(provider_data.get("country")),
                region=_string_or_none(entry.get("region"))
                or _string_or_none(entry.get("location")),
                is_spot=billing_type == "spot",
                availability_status="external_reference",
                raw_ref=raw_ref,
                metadata={
                    "upstream_provider_name": provider_data.get("name"),
                    "provider_website": provider_data.get("website"),
                    "external_id": entry.get("external_id"),
                    "gpu_slug": gpu_slug,
                    "source_vram_gb": source_vram_gb,
                    "billing_type": billing_type,
                    "hourly_per_gpu": pricing.get("hourly_per_gpu"),
                    "monthly_price": pricing.get("monthly"),
                    "pricing_note": pricing.get("note"),
                    "external_availability": status.get("availability"),
                    "external_status_note": status.get("note"),
                    "source_last_verified": status.get("last_verified"),
                    "interconnect": configuration.get("interconnect"),
                    "interconnect_bandwidth_gbps": configuration.get(
                        "interconnect_bandwidth_gbps"
                    ),
                    "cpu_cores": configuration.get("cpu_cores"),
                    "system_ram_gb": configuration.get("system_ram_gb"),
                    "disk_storage_gb": configuration.get("disk_storage_gb"),
                    "price_basis": "external_aggregator_reference",
                    "capacity_basis": None,
                    "benchmark_eligible": False,
                },
            )
        )

    return normalized, sorted(set(unknown_gpu_names))


def _extract_offerings(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, Mapping) or not isinstance(payload.get("data"), list):
        return []
    return [dict(row) for row in payload["data"] if isinstance(row, Mapping)]


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


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


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
