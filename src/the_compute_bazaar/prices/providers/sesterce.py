"""Sesterce live GPU Cloud offer adapter."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests

from ..normalize import canonical_gpu_model
from ..schemas import GpuOffer


DEFAULT_SESTERCE_API_BASE = "https://api.cloud.sesterce.com"


@dataclass(frozen=True)
class SesterceOffersFetch:
    raw_payload: dict[str, Any]
    offers: list[dict[str, Any]]


class SesterceClient:
    def __init__(
        self,
        *,
        api_key: str,
        api_base: str = DEFAULT_SESTERCE_API_BASE,
        session: requests.Session | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("Sesterce API key is required")
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.session = session or requests.Session()

    def fetch_offers(self) -> SesterceOffersFetch:
        query = {"available": "true", "sort": "price"}
        response = self.session.get(
            f"{self.api_base}/gpu-cloud/instances/offers",
            params=query,
            headers={"Accept": "application/json", "x-api-key": self.api_key},
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        offers = _extract_offers(payload)
        return SesterceOffersFetch(
            raw_payload={
                "query": query,
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
        gpu_name = str(entry.get("gpuName") or "")
        configuration = (
            entry.get("configuration")
            if isinstance(entry.get("configuration"), Mapping)
            else {}
        )
        vram_gb = _float_or_none(configuration.get("vRamGB"))
        gpu_model = canonical_gpu_model(gpu_name, vram_gb * 1024 if vram_gb else None)
        if not gpu_model:
            if gpu_name:
                unknown_gpu_names.append(gpu_name)
            continue

        gpu_count = _int_or_none(entry.get("gpuCount")) or 1
        price = _float_or_none(entry.get("hourlyPrice"))
        if price is None or price <= 0:
            continue
        if gpu_count > 1:
            gpu_model = f"{gpu_model}_x{gpu_count}"

        cloud = entry.get("cloud") if isinstance(entry.get("cloud"), Mapping) else {}
        availability = (
            entry.get("availability")
            if isinstance(entry.get("availability"), list)
            else []
        )
        for region_entry in availability:
            if (
                not isinstance(region_entry, Mapping)
                or region_entry.get("available") is not True
            ):
                continue
            region = str(region_entry.get("region") or "")
            country = str(region_entry.get("countryCode") or "") or None
            normalized.append(
                GpuOffer(
                    provider="sesterce",
                    source_offer_id=":".join(
                        part
                        for part in (
                            str(cloud.get("_id") or cloud.get("name") or ""),
                            str(entry.get("instanceId") or ""),
                            region,
                        )
                        if part
                    ),
                    observed_at=observed_at,
                    gpu_raw_name=gpu_name,
                    gpu_model=gpu_model,
                    gpu_count=gpu_count,
                    vram_gb=vram_gb,
                    price_usd_hr=price,
                    available_gpu_count=gpu_count,
                    country=country,
                    region=str(region_entry.get("name") or region) or None,
                    is_spot=False,
                    is_secure=None,
                    availability_status="available",
                    raw_ref=raw_ref,
                    metadata={
                        "upstream_provider": cloud.get("name"),
                        "cloud_id": cloud.get("_id"),
                        "instance_id": entry.get("instanceId"),
                        "deployment_type": entry.get("deploymentType"),
                        "interconnect": configuration.get("interconnect"),
                        "nvlink": entry.get("nvlink"),
                        "price_basis": "sesterce_instance_hour",
                        "capacity_basis": "available_region_bundle_lower_bound",
                    },
                )
            )

    return normalized, sorted(set(unknown_gpu_names))


def _extract_offers(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [dict(row) for row in payload if isinstance(row, Mapping)]
    if isinstance(payload, Mapping):
        for key in ("offers", "items", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [dict(row) for row in value if isinstance(row, Mapping)]
    return []


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
