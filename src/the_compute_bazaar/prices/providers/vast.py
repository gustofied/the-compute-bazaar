"""Vast.ai market data adapter."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

import requests

from ..normalize import canonical_gpu_model
from ..schemas import GpuOffer


DEFAULT_VAST_API_BASE = "https://console.vast.ai/api/v0"


class VastClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_base: str = DEFAULT_VAST_API_BASE,
        session: requests.Session | None = None,
    ) -> None:
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.session = session or requests.Session()

    def search_bundles(self, query: str | Mapping[str, Any] | None = None) -> dict[str, Any] | list[Any]:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        params: dict[str, str] = {}
        if query:
            params["q"] = query if isinstance(query, str) else json.dumps(query, separators=(",", ":"))

        response = self.session.get(
            f"{self.api_base}/bundles/",
            params=params,
            headers=headers,
            timeout=60,
        )
        response.raise_for_status()
        return response.json()


def extract_offers(payload: dict[str, Any] | list[Any]) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]

    for key in ("offers", "results", "machines", "bundles", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
        if isinstance(value, dict):
            nested = extract_offers(value)
            if nested:
                return nested
    return []


def normalize_offers(
    offers: Iterable[Mapping[str, Any]],
    *,
    observed_at: datetime,
    raw_ref: str | None,
) -> tuple[list[GpuOffer], list[str]]:
    normalized: list[GpuOffer] = []
    unknown_gpu_names: list[str] = []

    for entry in offers:
        offer = normalize_offer(entry, observed_at=observed_at, raw_ref=raw_ref)
        if offer is None:
            gpu_name = str(entry.get("gpu_name") or entry.get("gpuName") or "")
            if gpu_name:
                unknown_gpu_names.append(gpu_name)
            continue
        normalized.append(offer)

    return normalized, sorted(set(unknown_gpu_names))


def normalize_offer(
    entry: Mapping[str, Any],
    *,
    observed_at: datetime,
    raw_ref: str | None,
) -> GpuOffer | None:
    gpu_name = str(entry.get("gpu_name") or entry.get("gpuName") or "")
    if not gpu_name:
        return None

    gpu_ram_mb = _float_or_none(entry.get("gpu_ram") or entry.get("gpuRam"))
    gpu_model = canonical_gpu_model(gpu_name, gpu_ram_mb)
    if not gpu_model:
        return None

    gpu_count = int(entry.get("num_gpus") or entry.get("gpu_count") or entry.get("numGpus") or 1)
    if gpu_count > 1:
        gpu_model = f"{gpu_model}_x{gpu_count}"

    price = _price_usd_hr(entry)
    if price is None or price <= 0:
        return None

    source_offer_id = str(
        entry.get("id")
        or entry.get("ask_contract_id")
        or entry.get("machine_id")
        or entry.get("bundle_id")
        or f"{gpu_name}:{price}:{gpu_count}"
    )

    country, region = _location(entry)
    rentable = entry.get("rentable")
    availability_status = "available" if rentable is not False else "unavailable"

    return GpuOffer(
        provider="vast",
        source_offer_id=source_offer_id,
        observed_at=observed_at,
        gpu_raw_name=gpu_name,
        gpu_model=gpu_model,
        gpu_count=gpu_count,
        vram_gb=round(gpu_ram_mb / 1024, 2) if gpu_ram_mb else None,
        price_usd_hr=price,
        country=country,
        region=region,
        is_spot=_bool_or_none(entry.get("is_spot") or entry.get("spot")),
        is_secure=_bool_or_none(entry.get("verified") or entry.get("secure")),
        availability_status=availability_status,
        raw_ref=raw_ref,
        metadata={
            "cuda_max_good": entry.get("cuda_max_good"),
            "reliability": entry.get("reliability"),
            "verification": entry.get("verification"),
        },
    )


def _price_usd_hr(entry: Mapping[str, Any]) -> float | None:
    search = entry.get("search")
    if isinstance(search, Mapping):
        value = search.get("totalHour") or search.get("total_hour")
        parsed = _float_or_none(value)
        if parsed is not None:
            return parsed

    for key in ("dph_total", "dphTotal", "price_usd_hr", "hourly_cost", "price"):
        parsed = _float_or_none(entry.get(key))
        if parsed is not None:
            return parsed
    return None


def _location(entry: Mapping[str, Any]) -> tuple[str | None, str | None]:
    location = entry.get("geolocation") or entry.get("location")
    if isinstance(location, str) and location:
        parts = [part.strip() for part in location.split(",") if part.strip()]
        if len(parts) == 1:
            return parts[0], None
        return parts[0], ", ".join(parts[1:])

    country = entry.get("country")
    region = entry.get("region") or entry.get("city")
    return str(country) if country else None, str(region) if region else None


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
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "1"}:
            return True
        if lowered in {"false", "no", "0"}:
            return False
    return None

