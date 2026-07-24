"""Akash public GPU pricing and availability summary adapter."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests

from ..normalize import canonical_gpu_model
from ..schemas import GpuOffer


DEFAULT_AKASH_GPU_PRICES_URL = "https://console-api.akash.network/v1/gpu-prices"


@dataclass(frozen=True)
class AkashGpuPricesFetch:
    raw_payload: dict[str, Any]
    models: list[dict[str, Any]]


class AkashClient:
    def __init__(
        self,
        *,
        prices_url: str = DEFAULT_AKASH_GPU_PRICES_URL,
        session: requests.Session | None = None,
    ) -> None:
        self.prices_url = prices_url
        self.session = session or requests.Session()

    def fetch_gpu_prices(self) -> AkashGpuPricesFetch:
        response = self.session.get(
            self.prices_url,
            params={},
            headers={"Accept": "application/json"},
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        models = (
            [dict(row) for row in payload.get("models", []) if isinstance(row, Mapping)]
            if isinstance(payload, Mapping)
            else []
        )
        return AkashGpuPricesFetch(
            raw_payload={
                "mode": "live_gpu_price_and_availability_summary",
                "source_url": self.prices_url,
                "payload": payload,
                "model_count": len(models),
                "models": models,
            },
            models=models,
        )


def normalize_gpu_prices(
    models: Iterable[Mapping[str, Any]],
    *,
    observed_at: datetime,
    raw_ref: str | None,
) -> tuple[list[GpuOffer], list[str]]:
    normalized: list[GpuOffer] = []
    unknown_gpu_names: list[str] = []

    for entry in models:
        gpu_name = str(entry.get("model") or "")
        vram_gb = _gib_value(entry.get("ram"))
        gpu_model = canonical_gpu_model(gpu_name, vram_gb * 1024 if vram_gb else None)
        if not gpu_model:
            if gpu_name:
                unknown_gpu_names.append(gpu_name)
            continue

        price = entry.get("price") if isinstance(entry.get("price"), Mapping) else {}
        floor_price = _float_or_none(price.get("min"))
        availability = (
            entry.get("availability")
            if isinstance(entry.get("availability"), Mapping)
            else {}
        )
        provider_availability = (
            entry.get("providerAvailability")
            if isinstance(entry.get("providerAvailability"), Mapping)
            else {}
        )
        available_units = _int_or_none(availability.get("available")) or 0
        if floor_price is None or floor_price <= 0:
            continue

        normalized.append(
            GpuOffer(
                provider="akash",
                source_offer_id=":".join(
                    part
                    for part in (
                        gpu_name,
                        str(entry.get("ram") or ""),
                        str(entry.get("interface") or ""),
                    )
                    if part
                ),
                observed_at=observed_at,
                gpu_raw_name=gpu_name,
                gpu_model=gpu_model,
                gpu_count=1,
                vram_gb=vram_gb,
                price_usd_hr=floor_price,
                available_gpu_count=available_units if available_units > 0 else None,
                country=None,
                region="Akash Network",
                is_spot=None,
                is_secure=None,
                availability_status="available"
                if available_units > 0
                else "unavailable",
                raw_ref=raw_ref,
                metadata={
                    "interface": entry.get("interface"),
                    "available_gpu_units": available_units,
                    "total_gpu_units": availability.get("total"),
                    "available_provider_count": provider_availability.get("available"),
                    "total_provider_count": provider_availability.get("total"),
                    "median_price_usd_gpu_hr": price.get("med"),
                    "average_price_usd_gpu_hr": price.get("avg"),
                    "weighted_average_price_usd_gpu_hr": price.get("weightedAverage"),
                    "max_price_usd_gpu_hr": price.get("max"),
                    "price_basis": "akash_current_market_floor_gpu_hour",
                    "capacity_basis": "provider_available_gpu_units",
                },
            )
        )

    return normalized, sorted(set(unknown_gpu_names))


def _gib_value(value: Any) -> float | None:
    if value is None:
        return None
    match = re.search(r"\d+(?:\.\d+)?", str(value))
    return float(match.group()) if match else None


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
