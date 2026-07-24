"""Cloud GPU Prices public external catalog adapter."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests

from ..normalize import canonical_gpu_model
from ..schemas import GpuOffer
from .http import retrying_session


DEFAULT_CLOUD_GPU_PRICES_API_URL = (
    "https://cloudgpuprices.com/api/v1/offerings"
)
DEFAULT_FRONTIER_GPU_SLUGS = ("h100", "h200", "b200", "b300")
FRONTIER_GPU_DETAILS = {
    "h100": ("NVIDIA H100", 80.0),
    "h200": ("NVIDIA H200", 141.0),
    "b200": ("NVIDIA B200", 180.0),
    "b300": ("NVIDIA B300", 288.0),
}
PROVIDER_ALIASES = {
    "core_weave": "coreweave",
    "fal_ai": "fal_ai",
}
PICOS_PER_USD = 1_000_000_000_000


@dataclass(frozen=True)
class CloudGpuPricesFetch:
    raw_payload: dict[str, Any]
    offerings: list[dict[str, Any]]
    generated_at: str | None


class CloudGpuPricesClient:
    def __init__(
        self,
        *,
        api_url: str = DEFAULT_CLOUD_GPU_PRICES_API_URL,
        session: requests.Session | None = None,
    ) -> None:
        self.api_url = api_url
        self.session = session or retrying_session()

    def fetch_frontier_offerings(
        self,
        *,
        gpu_slugs: Sequence[str] = DEFAULT_FRONTIER_GPU_SLUGS,
        page_size: int = 100,
        max_pages: int = 10,
    ) -> CloudGpuPricesFetch:
        effective_page_size = max(1, min(int(page_size), 100))
        pages: list[dict[str, Any]] = []
        offerings: list[dict[str, Any]] = []
        cursor: str | None = None
        generated_at: str | None = None

        for page_number in range(1, max(1, int(max_pages)) + 1):
            params: dict[str, Any] = {
                "gpu": list(gpu_slugs),
                "currency": "USD",
                "limit": effective_page_size,
            }
            if cursor:
                params["cursor"] = cursor
            response = self.session.get(
                self.api_url,
                params=params,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "the-compute-bazaar/0.1",
                },
                timeout=60,
            )
            response.raise_for_status()
            payload = response.json()
            rows = _extract_offerings(payload)
            offerings.extend(rows)
            if generated_at is None and isinstance(payload, Mapping):
                generated_at = _string_or_none(payload.get("generated_at"))
            pages.append(
                {
                    "page": page_number,
                    "cursor": cursor,
                    "payload": payload,
                    "item_count": len(rows),
                }
            )
            next_cursor = _next_cursor(payload)
            if not rows or not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor

        return CloudGpuPricesFetch(
            raw_payload={
                "mode": "public_external_gpu_catalog",
                "source_url": self.api_url,
                "gpu_slugs": list(gpu_slugs),
                "page_size": effective_page_size,
                "page_count": len(pages),
                "item_count": len(offerings),
                "pages": pages,
            },
            offerings=offerings,
            generated_at=generated_at,
        )


def normalize_external_offerings(
    offerings: Iterable[Mapping[str, Any]],
    *,
    generated_at: str | None,
    fetched_at: datetime,
    raw_ref: str | None,
) -> tuple[list[GpuOffer], list[str]]:
    normalized: list[GpuOffer] = []
    unknown_gpu_names: list[str] = []

    for offering in offerings:
        offering_id = _string_or_none(offering.get("id"))
        provider_data = _mapping(offering.get("provider"))
        product = _mapping(offering.get("product"))
        hardware = _mapping(offering.get("hardware"))
        options = hardware.get("options")
        if not offering_id or not isinstance(options, list) or len(options) != 1:
            continue

        gpu_option = _mapping(options[0])
        gpu_slug = str(gpu_option.get("slug") or "").strip().lower()
        gpu_details = FRONTIER_GPU_DETAILS.get(gpu_slug)
        if gpu_details is None:
            unknown_name = _string_or_none(gpu_option.get("name"))
            if unknown_name:
                unknown_gpu_names.append(unknown_name)
            continue
        gpu_name, vram_gb = gpu_details
        source_vram_gb = _float_or_none(
            hardware.get("gpu_memory_per_device_gb")
            or hardware.get("gpu_memory_gb")
        )
        gpu_count = _int_or_none(hardware.get("gpu_count"))
        if gpu_count is None or gpu_count <= 0:
            continue

        gpu_model = canonical_gpu_model(gpu_name, vram_gb * 1024)
        if not gpu_model:
            unknown_gpu_names.append(gpu_name)
            continue
        if gpu_count > 1:
            gpu_model = f"{gpu_model}_x{gpu_count}"

        provider_name = _string_or_none(provider_data.get("name"))
        provider = _provider_id(str(provider_data.get("slug") or provider_name or ""))
        if not provider:
            continue
        provenance = _mapping(offering.get("provenance"))
        observed_at = (
            _parse_datetime(provenance.get("verified_at"))
            or _parse_datetime(provenance.get("fact_retrieved_at"))
            or _parse_datetime(generated_at)
            or fetched_at
        )
        variants = offering.get("variants")
        if not isinstance(variants, list):
            continue

        for variant_value in variants:
            variant = _mapping(variant_value)
            comparison = _mapping(variant.get("comparison"))
            if (
                comparison.get("fixed_gpu_eligible") is not True
                or comparison.get("total_price_eligible") is not True
            ):
                continue
            variant_id = _string_or_none(variant.get("id"))
            price_usd_hr = _picos_to_usd(
                comparison.get("comparable_hourly_amount_picos")
            )
            if not variant_id or price_usd_hr is None or price_usd_hr <= 0:
                continue

            purchase_option = str(
                variant.get("purchase_option") or ""
            ).strip().lower()
            interruption_policy = str(
                variant.get("interruption_policy") or ""
            ).strip().lower()
            region = _mapping(variant.get("region"))
            region_code = _string_or_none(variant.get("region_code"))
            normalized.append(
                GpuOffer(
                    provider=provider,
                    source_connector="cloud_gpu_prices",
                    source_offer_id=(
                        f"cloud_gpu_prices:{offering_id}:{variant_id}"
                    ),
                    observed_at=observed_at,
                    gpu_raw_name=gpu_name,
                    gpu_model=gpu_model,
                    gpu_count=gpu_count,
                    vram_gb=vram_gb,
                    price_usd_hr=price_usd_hr,
                    currency="USD",
                    country=_string_or_none(region.get("country_code")),
                    region=region_code,
                    is_spot=(
                        purchase_option == "spot"
                        or interruption_policy == "interruptible"
                    ),
                    availability_status="external_reference",
                    raw_ref=raw_ref,
                    metadata={
                        "upstream_provider_name": provider_name,
                        "product_slug": product.get("slug"),
                        "product_name": product.get("name"),
                        "product_category": product.get("category"),
                        "offering_name": offering.get("name"),
                        "variant_name": variant.get("name"),
                        "source_url": offering.get("source_url"),
                        "source_availability": offering.get("availability"),
                        "source_freshness": offering.get("freshness"),
                        "source_verified_at": provenance.get("verified_at"),
                        "source_generated_at": generated_at,
                        "source_vram_gb": source_vram_gb,
                        "hardware_selection": hardware.get("selection"),
                        "purchase_option": purchase_option,
                        "operating_mode": variant.get("operating_mode"),
                        "tenancy": variant.get("tenancy"),
                        "interruption_policy": interruption_policy,
                        "pricing_structure": comparison.get("pricing_structure"),
                        "reason_codes": comparison.get("reason_codes"),
                        "billing_increment_ms": variant.get(
                            "billing_increment_ms"
                        ),
                        "minimum_billable_ms": variant.get(
                            "minimum_billable_ms"
                        ),
                        "billable_states": variant.get("billable_states"),
                        "price_basis": (
                            "external_aggregator_comparable_instance_hour"
                        ),
                        "capacity_basis": None,
                        "benchmark_eligible": False,
                    },
                )
            )

    return normalized, sorted(set(unknown_gpu_names))


def _extract_offerings(payload: Any) -> list[dict[str, Any]]:
    if (
        not isinstance(payload, Mapping)
        or not isinstance(payload.get("offerings"), list)
    ):
        return []
    return [
        dict(offering)
        for offering in payload["offerings"]
        if isinstance(offering, Mapping)
    ]


def _next_cursor(payload: Any) -> str | None:
    if not isinstance(payload, Mapping):
        return None
    pagination = _mapping(payload.get("pagination"))
    return _string_or_none(pagination.get("next_cursor"))


def _provider_id(value: str) -> str:
    normalized = (
        value.strip()
        .lower()
        .replace(".", "_")
        .replace("-", "_")
        .replace(" ", "_")
    ).strip("_")
    return PROVIDER_ALIASES.get(normalized, normalized)


def _picos_to_usd(value: Any) -> float | None:
    amount = _float_or_none(value)
    return amount / PICOS_PER_USD if amount is not None else None


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


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


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
