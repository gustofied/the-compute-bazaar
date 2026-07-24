"""Spheron live multi-provider GPU offer feed."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests

from ..normalize import canonical_gpu_model
from ..schemas import GpuOffer


DEFAULT_SPHERON_OFFERS_URL = "https://app.spheron.ai/api/gpu-offers"


@dataclass(frozen=True)
class SpheronOffersFetch:
    raw_payload: dict[str, Any]
    offers: list[dict[str, Any]]


class SpheronClient:
    def __init__(
        self,
        *,
        offers_url: str = DEFAULT_SPHERON_OFFERS_URL,
        session: requests.Session | None = None,
    ) -> None:
        self.offers_url = offers_url
        self.session = session or requests.Session()

    def fetch_offers(self) -> SpheronOffersFetch:
        response = self.session.get(
            self.offers_url,
            params={},
            headers={"Accept": "application/json"},
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        groups = payload.get("data") if isinstance(payload, Mapping) else None
        offers: list[dict[str, Any]] = []
        if isinstance(groups, list):
            for group in groups:
                if not isinstance(group, Mapping):
                    continue
                group_offers = group.get("offers")
                if not isinstance(group_offers, list):
                    continue
                for offer in group_offers:
                    if not isinstance(offer, Mapping):
                        continue
                    offers.append(
                        {
                            **dict(offer),
                            "_gpu_type": group.get("gpuType"),
                            "_gpu_model": group.get("gpuModel"),
                            "_display_name": group.get("displayName"),
                        }
                    )
        return SpheronOffersFetch(
            raw_payload={
                "mode": "live_gpu_offer_feed",
                "source_url": self.offers_url,
                "payload": payload,
                "offer_count": len(offers),
                "offers": offers,
            },
            offers=offers,
        )


def normalize_offers(
    offers: Iterable[Mapping[str, Any]],
    *,
    observed_at: datetime,
    raw_ref: str | None,
) -> tuple[list[GpuOffer], list[str]]:
    normalized: list[GpuOffer] = []
    unknown_gpu_names: list[str] = []

    for entry in offers:
        gpu_name = str(
            entry.get("_display_name")
            or entry.get("_gpu_type")
            or entry.get("_gpu_model")
            or ""
        )
        vram_gb = _float_or_none(entry.get("gpu_memory"))
        gpu_model = canonical_gpu_model(gpu_name, vram_gb * 1024 if vram_gb else None)
        if not gpu_model:
            if gpu_name:
                unknown_gpu_names.append(gpu_name)
            continue

        gpu_count = _int_or_none(entry.get("gpuCount")) or 1
        price = _float_or_none(entry.get("price"))
        if price is None or price <= 0:
            continue
        if gpu_count > 1:
            gpu_model = f"{gpu_model}_x{gpu_count}"

        is_spot = entry.get("spot_price") is not None or str(
            entry.get("offerId") or ""
        ).endswith("::spot")
        is_available = (
            entry.get("available") is True and entry.get("maintenance") is not True
        )
        if is_spot:
            availability_status = (
                "spot_available" if is_available else "spot_unavailable"
            )
        else:
            availability_status = "available" if is_available else "unavailable"

        clusters = (
            entry.get("clusters") if isinstance(entry.get("clusters"), list) else []
        )
        extras = entry.get("extras") if isinstance(entry.get("extras"), Mapping) else {}
        technical = (
            extras.get("technical")
            if isinstance(extras.get("technical"), Mapping)
            else {}
        )
        available_units = _int_or_none(technical.get("units_available"))
        available_gpu_count = None
        if is_available:
            available_gpu_count = (
                available_units * gpu_count
                if available_units is not None and available_units > 0
                else gpu_count
            )
        upstream_provider = str(entry.get("provider") or "").strip()
        provider = _provider_id(upstream_provider)
        normalized.append(
            GpuOffer(
                provider=provider,
                source_offer_id=str(entry.get("offerId") or entry.get("name") or ""),
                observed_at=observed_at,
                gpu_raw_name=gpu_name,
                gpu_model=gpu_model,
                gpu_count=gpu_count,
                vram_gb=vram_gb,
                price_usd_hr=price,
                available_gpu_count=available_gpu_count,
                source_connector="spheron",
                country=None,
                region=", ".join(str(cluster) for cluster in clusters) or None,
                is_spot=is_spot,
                is_secure=None,
                availability_status=availability_status,
                raw_ref=raw_ref,
                metadata={
                    "upstream_provider": upstream_provider or None,
                    "interconnect": entry.get("interconnectType"),
                    "maintenance": entry.get("maintenance"),
                    "units_available": technical.get("units_available"),
                    "availability_level": technical.get("availability_level"),
                    "deployment_type": extras.get("deployment_type"),
                    "price_basis": "spheron_instance_hour",
                    "capacity_basis": (
                        "provider_deployable_units"
                        if available_units is not None and available_units > 0
                        else "available_offer_bundle"
                    ),
                },
            )
        )

    return normalized, sorted(set(unknown_gpu_names))


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


def _provider_id(value: str) -> str:
    normalized = value.strip().lower()
    aliases = {
        "data-crunch": "datacrunch",
        "massed-compute": "massed_compute",
        "spheron-ai": "spheron",
        "spheron-es": "spheron",
    }
    return aliases.get(normalized, normalized.replace("-", "_")) or "spheron"
