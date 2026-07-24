"""Azure public retail-prices API adapter for frontier GPU VM rates."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests

from ..schemas import GpuOffer
from .http import retrying_session


DEFAULT_AZURE_RETAIL_PRICES_URL = "https://prices.azure.com/api/retail/prices"

# SKU shape comes from Azure's official VM-size documentation. GB200 and GB300
# are purchasable VM packages whose accelerators are B200 and B300 GPUs.
AZURE_FRONTIER_SKUS: tuple[dict[str, Any], ...] = (
    {
        "arm_sku_name": "Standard_ND96isr_H100_v5",
        "gpu_raw_name": "NVIDIA H100",
        "gpu_model": "H100_80GB",
        "gpu_count": 8,
        "vram_gb": 80.0,
        "package_model": "ND H100 v5",
    },
    {
        "arm_sku_name": "Standard_ND96isr_H200_v5",
        "gpu_raw_name": "NVIDIA H200",
        "gpu_model": "H200_141GB",
        "gpu_count": 8,
        "vram_gb": 141.0,
        "package_model": "ND H200 v5",
    },
    {
        "arm_sku_name": "Standard_ND128isr_NDR_GB200_v6",
        "gpu_raw_name": "NVIDIA B200 in GB200 NVL72",
        "gpu_model": "B200_180GB",
        "gpu_count": 4,
        "vram_gb": 192.0,
        "package_model": "GB200 NVL72",
    },
    {
        "arm_sku_name": "Standard_ND128isr_GB300_v6",
        "gpu_raw_name": "NVIDIA B300 in GB300 NVL72",
        "gpu_model": "B300_288GB",
        "gpu_count": 4,
        "vram_gb": 288.0,
        "package_model": "GB300 NVL72",
    },
)


@dataclass(frozen=True)
class AzureRetailFetch:
    raw_payload: dict[str, Any]
    prices: list[dict[str, Any]]


class AzureRetailClient:
    def __init__(
        self,
        *,
        prices_url: str = DEFAULT_AZURE_RETAIL_PRICES_URL,
        session: requests.Session | None = None,
    ) -> None:
        self.prices_url = prices_url
        self.session = session or retrying_session()

    def fetch_frontier_prices(
        self,
        *,
        sku_specs: Iterable[Mapping[str, Any]] = AZURE_FRONTIER_SKUS,
        max_pages_per_sku: int = 10,
    ) -> AzureRetailFetch:
        specs = [dict(spec) for spec in sku_specs]
        pages: list[dict[str, Any]] = []
        prices: list[dict[str, Any]] = []

        arm_sku_names = [str(spec["arm_sku_name"]) for spec in specs]
        url: str | None = self.prices_url
        params: dict[str, Any] = {
            "$filter": " or ".join(
                f"armSkuName eq '{arm_sku_name}'" for arm_sku_name in arm_sku_names
            ),
            "$top": 1000,
        }
        for page_number in range(1, max(1, max_pages_per_sku) + 1):
            assert url is not None
            response = self.session.get(
                url,
                params=params,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "the-compute-bazaar/0.1",
                },
                timeout=60,
            )
            response.raise_for_status()
            payload = response.json()
            page_items = _mapping_items(payload)
            prices.extend(page_items)
            pages.append(
                {
                    "arm_sku_names": arm_sku_names,
                    "page": page_number,
                    "request_url": url,
                    "payload": payload,
                    "item_count": len(page_items),
                }
            )
            next_page = (
                payload.get("NextPageLink") if isinstance(payload, Mapping) else None
            )
            if not next_page:
                break
            url = str(next_page)
            params = {}

        return AzureRetailFetch(
            raw_payload={
                "mode": "public_retail_prices_api",
                "source_url": self.prices_url,
                "sku_specs": specs,
                "page_count": len(pages),
                "item_count": len(prices),
                "pages": pages,
            },
            prices=prices,
        )


def normalize_retail_prices(
    prices: Iterable[Mapping[str, Any]],
    *,
    observed_at: datetime,
    raw_ref: str | None,
    sku_specs: Iterable[Mapping[str, Any]] = AZURE_FRONTIER_SKUS,
) -> tuple[list[GpuOffer], list[str]]:
    specs_by_sku = {str(spec["arm_sku_name"]): dict(spec) for spec in sku_specs}
    normalized: list[GpuOffer] = []
    unknown_skus: list[str] = []

    for entry in prices:
        arm_sku_name = str(entry.get("armSkuName") or "")
        spec = specs_by_sku.get(arm_sku_name)
        if spec is None:
            if arm_sku_name:
                unknown_skus.append(arm_sku_name)
            continue
        if not _is_comparable_hourly_linux_rate(entry):
            continue

        price = _float_or_none(entry.get("retailPrice"))
        if price is None or price <= 0:
            continue
        gpu_count = int(spec["gpu_count"])
        is_spot = _is_spot_rate(entry)
        effective_start = _parse_datetime(entry.get("effectiveStartDate"))
        effective_end = _parse_datetime(entry.get("effectiveEndDate"))
        is_future = effective_start is not None and effective_start > observed_at
        is_expired = effective_end is not None and effective_end <= observed_at
        if is_expired:
            availability_status = "published_rate_expired"
        elif is_future:
            availability_status = "published_rate_future"
        elif is_spot:
            availability_status = "spot_price_observed"
        else:
            availability_status = "published_rate"

        gpu_model = str(spec["gpu_model"])
        if gpu_count > 1:
            gpu_model = f"{gpu_model}_x{gpu_count}"
        region = _string_or_none(entry.get("armRegionName")) or _string_or_none(
            entry.get("location")
        )
        meter_id = str(entry.get("meterId") or entry.get("skuId") or "")
        rate_kind = "spot" if is_spot else "ondemand"

        normalized.append(
            GpuOffer(
                provider="azure",
                source_offer_id=":".join(
                    part for part in (arm_sku_name, region, meter_id, rate_kind) if part
                ),
                observed_at=observed_at,
                gpu_raw_name=str(spec["gpu_raw_name"]),
                gpu_model=gpu_model,
                gpu_count=gpu_count,
                vram_gb=float(spec["vram_gb"]),
                price_usd_hr=price,
                currency="USD",
                country=None,
                region=region,
                is_spot=is_spot,
                is_secure=True,
                availability_status=availability_status,
                raw_ref=raw_ref,
                metadata={
                    "arm_sku_name": arm_sku_name,
                    "package_model": spec["package_model"],
                    "accelerator_model": str(spec["gpu_model"]).split("_", 1)[0],
                    "meter_id": entry.get("meterId"),
                    "meter_name": entry.get("meterName"),
                    "product_name": entry.get("productName"),
                    "sku_name": entry.get("skuName"),
                    "sku_id": entry.get("skuId"),
                    "location": entry.get("location"),
                    "effective_start_date": entry.get("effectiveStartDate"),
                    "effective_end_date": entry.get("effectiveEndDate"),
                    "is_primary_meter_region": entry.get("isPrimaryMeterRegion"),
                    "capacity_confirmed": False,
                    "price_basis": (
                        "azure_retail_spot_vm_hour"
                        if is_spot
                        else "azure_retail_on_demand_vm_hour"
                    ),
                },
            )
        )

    return normalized, sorted(set(unknown_skus))


def _mapping_items(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, Mapping) or not isinstance(payload.get("Items"), list):
        return []
    return [dict(item) for item in payload["Items"] if isinstance(item, Mapping)]


def _is_comparable_hourly_linux_rate(entry: Mapping[str, Any]) -> bool:
    product_name = str(entry.get("productName") or "")
    return (
        str(entry.get("currencyCode") or "").upper() == "USD"
        and str(entry.get("unitOfMeasure") or "") == "1 Hour"
        and str(entry.get("serviceName") or "") == "Virtual Machines"
        and str(entry.get("type") or "") == "Consumption"
        and "windows" not in product_name.lower()
        and entry.get("isPrimaryMeterRegion") is not False
    )


def _is_spot_rate(entry: Mapping[str, Any]) -> bool:
    return (
        "spot"
        in " ".join(
            str(entry.get(key) or "") for key in ("meterName", "skuName", "productName")
        ).lower()
    )


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


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
