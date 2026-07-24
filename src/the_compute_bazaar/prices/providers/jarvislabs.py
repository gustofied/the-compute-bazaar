"""JarvisLabs authenticated live GPU price and free-device adapter."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests

from ..normalize import canonical_gpu_model
from ..schemas import GpuOffer
from .http import retrying_session


DEFAULT_JARVISLABS_API_BASE = "https://backendn.jarvislabs.net"


@dataclass(frozen=True)
class JarvisLabsAvailabilityFetch:
    raw_payload: dict[str, Any]
    rows: list[dict[str, Any]]


class JarvisLabsClient:
    def __init__(
        self,
        *,
        api_key: str,
        api_base: str = DEFAULT_JARVISLABS_API_BASE,
        session: requests.Session | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("JarvisLabs API key is required")
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.session = session or retrying_session()

    def fetch_gpu_availability(self) -> JarvisLabsAvailabilityFetch:
        response = self.session.get(
            f"{self.api_base}/misc/server_meta",
            params={},
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        rows = _extract_rows(payload)
        return JarvisLabsAvailabilityFetch(
            raw_payload={
                "mode": "authenticated_live_gpu_availability",
                "source_url": f"{self.api_base}/misc/server_meta",
                "payload": payload,
                "row_count": len(rows),
                "rows": rows,
            },
            rows=rows,
        )


def normalize_gpu_availability(
    rows: Iterable[Mapping[str, Any]],
    *,
    observed_at: datetime,
    raw_ref: str | None,
) -> tuple[list[GpuOffer], list[str]]:
    normalized: list[GpuOffer] = []
    unknown_gpu_names: list[str] = []

    for entry in rows:
        gpu_name = str(entry.get("gpu_type") or "").strip()
        vram_gb = _vram_gb(entry.get("vram"))
        gpu_model = canonical_gpu_model(
            gpu_name,
            vram_gb * 1024 if vram_gb is not None else None,
        )
        if not gpu_model:
            if gpu_name:
                unknown_gpu_names.append(gpu_name)
            continue

        reported_free = _int_or_none(entry.get("num_free_devices")) or 0
        effective_free = _int_or_none(entry.get("effective_num_free_devices"))
        available_count = max(
            0, effective_free if effective_free is not None else reported_free
        )
        region = str(entry.get("region") or "global").strip()
        on_demand_price = _float_or_none(entry.get("price_per_hour"))
        spot_price = _float_or_none(entry.get("spot_price"))
        price_modes = [
            ("on_demand", on_demand_price, False),
            ("spot", spot_price, True),
        ]
        capacity_assigned = False

        for price_mode, price, is_spot in price_modes:
            if price is None or price <= 0:
                continue
            is_available = available_count > 0
            row_capacity = (
                available_count if is_available and not capacity_assigned else None
            )
            if row_capacity:
                capacity_assigned = True
            if is_spot:
                availability_status = (
                    "spot_available" if is_available else "spot_price_observed"
                )
            else:
                availability_status = "available" if is_available else "unavailable"

            normalized.append(
                GpuOffer(
                    provider="jarvislabs",
                    source_connector="jarvislabs",
                    source_offer_id=f"{region}:{gpu_name}:{price_mode}",
                    observed_at=observed_at,
                    gpu_raw_name=gpu_name,
                    gpu_model=gpu_model,
                    gpu_count=1,
                    vram_gb=vram_gb,
                    price_usd_hr=price,
                    available_gpu_count=row_capacity,
                    country=_country_for_region(region),
                    region=region,
                    is_spot=is_spot,
                    is_secure=True,
                    availability_status=availability_status,
                    raw_ref=raw_ref,
                    metadata={
                        "num_free_devices": reported_free,
                        "effective_num_free_devices": effective_free,
                        "architecture": entry.get("arc"),
                        "cpus_per_gpu": entry.get("cpus_per_gpu"),
                        "ram_per_gpu": entry.get("ram_per_gpu"),
                        "workload_type": entry.get("workload_type"),
                        "price_basis": f"jarvislabs_{price_mode}_gpu_hour",
                        "capacity_basis": (
                            "provider_reported_free_devices" if row_capacity else None
                        ),
                    },
                )
            )

    return normalized, sorted(set(unknown_gpu_names))


def _extract_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [dict(row) for row in payload if isinstance(row, Mapping)]
    if isinstance(payload, Mapping):
        for key in ("server_meta", "data"):
            if isinstance(payload.get(key), list):
                return [dict(row) for row in payload[key] if isinstance(row, Mapping)]
    return []


def _vram_gb(value: Any) -> float | None:
    if value is None:
        return None
    match = re.search(r"\d+(?:\.\d+)?", str(value))
    return float(match.group(0)) if match else None


def _country_for_region(region: str) -> str | None:
    if region.startswith("india-"):
        return "IN"
    return None


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
