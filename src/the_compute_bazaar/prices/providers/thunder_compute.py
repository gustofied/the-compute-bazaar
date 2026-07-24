"""Thunder Compute public GPU pricing and availability adapter."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests

from ..normalize import canonical_gpu_model
from ..schemas import GpuOffer
from .http import retrying_session


DEFAULT_THUNDER_API_BASE = "https://api.thundercompute.com:8443"
_SPEC_PATTERN = re.compile(r"^(?P<gpu>[a-z0-9]+?)(?:_x(?P<count>\d+))?$")
_GPU_DETAILS = {
    "a100xl": ("NVIDIA A100 80GB", 80.0),
    "a6000": ("NVIDIA RTX A6000", 48.0),
    "h100": ("NVIDIA H100 PCIe", 80.0),
    "l40": ("NVIDIA L40", 48.0),
    "l40s": ("NVIDIA L40S", 48.0),
}


@dataclass(frozen=True)
class ThunderCatalogFetch:
    raw_payload: dict[str, Any]
    pricing: dict[str, Any]
    availability: dict[str, Any]


class ThunderComputeClient:
    def __init__(
        self,
        *,
        api_base: str = DEFAULT_THUNDER_API_BASE,
        session: requests.Session | None = None,
    ) -> None:
        self.api_base = api_base.rstrip("/")
        self.session = session or retrying_session()

    def fetch_catalog(self) -> ThunderCatalogFetch:
        pricing_response = self.session.get(
            f"{self.api_base}/v2/pricing",
            params={},
            headers={"Accept": "application/json"},
            timeout=60,
        )
        pricing_response.raise_for_status()
        pricing_payload = pricing_response.json()

        availability_response = self.session.get(
            f"{self.api_base}/v2/status",
            params={},
            headers={"Accept": "application/json"},
            timeout=60,
        )
        availability_response.raise_for_status()
        availability_payload = availability_response.json()

        pricing = _mapping_value(pricing_payload, "pricing")
        availability = (
            dict(availability_payload)
            if isinstance(availability_payload, Mapping)
            else {}
        )
        return ThunderCatalogFetch(
            raw_payload={
                "mode": "public_live_pricing_and_availability",
                "pricing_url": f"{self.api_base}/v2/pricing",
                "availability_url": f"{self.api_base}/v2/status",
                "pricing_payload": pricing_payload,
                "availability_payload": availability_payload,
                "spec_count": len(_mapping_value(availability, "specs")),
            },
            pricing=pricing,
            availability=availability,
        )


def normalize_catalog(
    pricing: Mapping[str, Any],
    availability: Mapping[str, Any],
    *,
    observed_at: datetime,
    raw_ref: str | None,
) -> tuple[list[GpuOffer], list[str]]:
    normalized: list[GpuOffer] = []
    unknown_gpu_names: list[str] = []
    statuses = _mapping_value(availability, "specs")

    for spec_key, status_value in statuses.items():
        price = _float_or_none(pricing.get(spec_key))
        if price is None or price <= 0:
            continue
        match = _SPEC_PATTERN.fullmatch(str(spec_key).strip().lower())
        if not match:
            continue
        gpu_key = match.group("gpu")
        details = _GPU_DETAILS.get(gpu_key)
        if details is None:
            unknown_gpu_names.append(gpu_key)
            continue

        gpu_name, vram_gb = details
        gpu_count = int(match.group("count") or 1)
        gpu_model = canonical_gpu_model(gpu_name, vram_gb * 1024)
        if not gpu_model:
            unknown_gpu_names.append(gpu_name)
            continue
        if gpu_count > 1:
            gpu_model = f"{gpu_model}_x{gpu_count}"

        status = str(status_value or "").strip().lower()
        is_available = status == "available"
        normalized.append(
            GpuOffer(
                provider="thunder_compute",
                source_connector="thunder_compute",
                source_offer_id=str(spec_key),
                observed_at=observed_at,
                gpu_raw_name=gpu_name,
                gpu_model=gpu_model,
                gpu_count=gpu_count,
                vram_gb=vram_gb,
                price_usd_hr=price,
                available_gpu_count=gpu_count if is_available else None,
                country=None,
                region="north_america",
                is_spot=False,
                is_secure=True,
                availability_status="available" if is_available else "unavailable",
                raw_ref=raw_ref,
                metadata={
                    "spec_key": spec_key,
                    "provider_status": status,
                    "price_basis": "thunder_current_instance_hour",
                    "capacity_basis": (
                        "available_bundle_lower_bound" if is_available else None
                    ),
                },
            )
        )

    return normalized, sorted(set(unknown_gpu_names))


def _mapping_value(payload: Any, key: str) -> dict[str, Any]:
    if isinstance(payload, Mapping) and isinstance(payload.get(key), Mapping):
        return dict(payload[key])
    return {}


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
