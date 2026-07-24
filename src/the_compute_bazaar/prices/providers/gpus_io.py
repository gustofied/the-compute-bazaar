"""GPUs.io authenticated live multi-provider price feed."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests

from ..normalize import canonical_gpu_model
from ..schemas import GpuOffer
from .http import retrying_session


DEFAULT_GPUS_IO_API_BASE = "https://api.gpus.io/v1"
PROVIDER_ALIASES = {
    "lambdalabs": "lambda",
    "massedcompute": "massed_compute",
}


@dataclass(frozen=True)
class GpusIoPricesFetch:
    raw_payload: dict[str, Any]
    prices: list[dict[str, Any]]


class GpusIoClient:
    def __init__(
        self,
        *,
        api_key: str,
        api_base: str = DEFAULT_GPUS_IO_API_BASE,
        session: requests.Session | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("GPUs.io API key is required")
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.session = session or retrying_session()

    def fetch_prices(
        self,
        *,
        max_pages: int = 20,
        page_size: int = 200,
    ) -> GpusIoPricesFetch:
        pages: list[dict[str, Any]] = []
        prices: list[dict[str, Any]] = []
        cursor: str | None = None
        effective_page_size = max(1, min(int(page_size), 200))

        for page_number in range(1, max(1, int(max_pages)) + 1):
            params: dict[str, Any] = {"limit": effective_page_size}
            if cursor:
                params["cursor"] = cursor
            response = self.session.get(
                f"{self.api_base}/prices",
                params=params,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                },
                timeout=60,
            )
            response.raise_for_status()
            payload = response.json()
            rows = _extract_prices(payload)
            prices.extend(rows)
            pages.append(
                {
                    "page": page_number,
                    "cursor": cursor,
                    "payload": payload,
                    "item_count": len(rows),
                }
            )
            next_cursor = _next_cursor(payload)
            if not next_cursor or next_cursor == cursor or not rows:
                break
            cursor = next_cursor

        return GpusIoPricesFetch(
            raw_payload={
                "mode": "authenticated_live_price_feed",
                "source_url": f"{self.api_base}/prices",
                "page_size": effective_page_size,
                "page_count": len(pages),
                "item_count": len(prices),
                "pages": pages,
                "prices": prices,
            },
            prices=prices,
        )


def normalize_prices(
    prices: Iterable[Mapping[str, Any]],
    *,
    observed_at: datetime,
    raw_ref: str | None,
) -> tuple[list[GpuOffer], list[str]]:
    normalized: list[GpuOffer] = []
    unknown_gpu_names: list[str] = []

    for entry in prices:
        gpu = entry.get("gpu") if isinstance(entry.get("gpu"), Mapping) else {}
        provider_data = (
            entry.get("provider") if isinstance(entry.get("provider"), Mapping) else {}
        )
        gpu_name = str(gpu.get("name") or gpu.get("key") or "")
        vram_gb = _float_or_none(gpu.get("vramGb"))
        gpu_model = canonical_gpu_model(
            gpu_name,
            vram_gb * 1024 if vram_gb is not None else None,
        )
        if not gpu_model:
            if gpu_name:
                unknown_gpu_names.append(gpu_name)
            continue

        gpu_count = _int_or_none(entry.get("gpuCount")) or 1
        if gpu_count > 1:
            gpu_model = f"{gpu_model}_x{gpu_count}"
        total_price = _float_or_none(entry.get("totalPricePerHourUsd"))
        per_gpu_price = _float_or_none(entry.get("pricePerGpuHourUsd"))
        if total_price is None and per_gpu_price is not None:
            total_price = per_gpu_price * gpu_count
        if total_price is None or total_price <= 0:
            continue

        provider_id = str(provider_data.get("id") or "").strip().lower()
        provider = PROVIDER_ALIASES.get(provider_id, provider_id)
        if not provider:
            continue
        rental_type = str(entry.get("rentalType") or "on_demand").strip().lower()
        available = entry.get("available") is True
        regions = entry.get("regions") if isinstance(entry.get("regions"), list) else []
        region_values = sorted(
            {str(region).strip() for region in regions if str(region or "").strip()}
        ) or ["global"]
        availability_status = _availability_status(
            rental_type=rental_type,
            available=available,
        )
        specs = entry.get("specs") if isinstance(entry.get("specs"), Mapping) else {}

        for region in region_values:
            normalized.append(
                GpuOffer(
                    provider=provider,
                    source_connector="gpus_io",
                    source_offer_id=_source_offer_id(
                        entry=entry,
                        provider=provider,
                        gpu_key=str(gpu.get("key") or gpu_name),
                        gpu_count=gpu_count,
                        rental_type=rental_type,
                        region=region,
                    ),
                    observed_at=observed_at,
                    gpu_raw_name=gpu_name,
                    gpu_model=gpu_model,
                    gpu_count=gpu_count,
                    vram_gb=vram_gb,
                    price_usd_hr=total_price,
                    available_gpu_count=(
                        gpu_count
                        if available and rental_type in {"on_demand", "spot"}
                        else None
                    ),
                    country=region if len(region) == 2 else None,
                    region=region,
                    is_spot=rental_type == "spot",
                    is_secure=None,
                    availability_status=availability_status,
                    raw_ref=raw_ref,
                    metadata={
                        "provider_name": provider_data.get("name"),
                        "provider_website": provider_data.get("website"),
                        "gpu_key": gpu.get("key"),
                        "rental_type": rental_type,
                        "commitment_term_months": entry.get("commitmentTermMonths"),
                        "price_per_gpu_hour_usd": per_gpu_price,
                        "last_updated": entry.get("lastUpdated"),
                        "vcpus": specs.get("vcpu"),
                        "ram_gb": specs.get("ramGb"),
                        "boot_disk_gb": specs.get("bootDiskGb"),
                        "scratch_disk_gb": specs.get("scratchDiskGb"),
                        "price_basis": "gpus_io_current_configuration_hour",
                        "capacity_basis": (
                            "bookable_region_bundle_lower_bound"
                            if available and rental_type in {"on_demand", "spot"}
                            else None
                        ),
                    },
                )
            )

    return normalized, sorted(set(unknown_gpu_names))


def _extract_prices(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, Mapping) or not isinstance(payload.get("data"), list):
        return []
    return [dict(row) for row in payload["data"] if isinstance(row, Mapping)]


def _next_cursor(payload: Any) -> str | None:
    if not isinstance(payload, Mapping):
        return None
    pagination = (
        payload.get("pagination")
        if isinstance(payload.get("pagination"), Mapping)
        else {}
    )
    value = pagination.get("nextCursor")
    return str(value) if value else None


def _availability_status(*, rental_type: str, available: bool) -> str:
    if rental_type == "spot":
        return "spot_available" if available else "spot_unavailable"
    if rental_type == "reserved":
        return "published_rate_reserved"
    return "available" if available else "unavailable"


def _source_offer_id(
    *,
    entry: Mapping[str, Any],
    provider: str,
    gpu_key: str,
    gpu_count: int,
    rental_type: str,
    region: str,
) -> str:
    return ":".join(
        [
            provider,
            gpu_key,
            str(gpu_count),
            rental_type,
            str(entry.get("commitmentTermMonths") or "none"),
            region,
        ]
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
