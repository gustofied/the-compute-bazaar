"""Shadeform live multi-cloud instance inventory adapter."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests

from ..normalize import canonical_gpu_model
from ..schemas import GpuOffer


DEFAULT_SHADEFORM_API_BASE = "https://api.shadeform.ai/v1"
PROVIDER_ALIASES = {
    "lambda_labs": "lambda",
    "lambdalabs": "lambda",
    "massed_compute": "massed_compute",
    "massedcompute": "massed_compute",
}


@dataclass(frozen=True)
class ShadeformTypesFetch:
    raw_payload: dict[str, Any]
    instance_types: list[dict[str, Any]]


class ShadeformClient:
    def __init__(
        self,
        *,
        api_key: str,
        api_base: str = DEFAULT_SHADEFORM_API_BASE,
        session: requests.Session | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("Shadeform API key is required")
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.session = session or requests.Session()

    def fetch_instance_types(self) -> ShadeformTypesFetch:
        query = {"available": "true", "sort": "price"}
        response = self.session.get(
            f"{self.api_base}/instances/types",
            params=query,
            headers={"Accept": "application/json", "X-API-KEY": self.api_key},
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        instance_types = _extract_instance_types(payload)
        return ShadeformTypesFetch(
            raw_payload={
                "query": query,
                "payload": payload,
                "instance_type_count": len(instance_types),
                "instance_types": instance_types,
            },
            instance_types=instance_types,
        )


def normalize_instance_types(
    instance_types: Iterable[Mapping[str, Any]],
    *,
    observed_at: datetime,
    raw_ref: str | None,
) -> tuple[list[GpuOffer], list[str]]:
    normalized: list[GpuOffer] = []
    unknown_gpu_names: list[str] = []

    for entry in instance_types:
        configuration = (
            entry.get("configuration")
            if isinstance(entry.get("configuration"), Mapping)
            else {}
        )
        gpu_name = str(configuration.get("gpu_type") or entry.get("gpu_type") or "")
        vram_gb = _float_or_none(
            configuration.get("vram_per_gpu_in_gb") or entry.get("vram_per_gpu_in_gb")
        )
        gpu_model = canonical_gpu_model(gpu_name, vram_gb * 1024 if vram_gb else None)
        if not gpu_model:
            if gpu_name:
                unknown_gpu_names.append(gpu_name)
            continue

        gpu_count = (
            _int_or_none(configuration.get("num_gpus") or entry.get("num_gpus")) or 1
        )
        hourly_cents = _float_or_none(entry.get("hourly_price"))
        if hourly_cents is None or hourly_cents <= 0:
            continue
        if gpu_count > 1:
            gpu_model = f"{gpu_model}_x{gpu_count}"

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
            cloud = str(entry.get("cloud") or "")
            provider = _provider_id(cloud)
            cloud_instance_type = str(entry.get("cloud_instance_type") or "")
            shade_instance_type = str(entry.get("shade_instance_type") or "")
            region = str(region_entry.get("region") or "")
            display_name = str(region_entry.get("display_name") or "")
            normalized.append(
                GpuOffer(
                    provider=provider,
                    source_connector="shadeform",
                    source_offer_id=":".join(
                        part
                        for part in (
                            cloud,
                            cloud_instance_type or shade_instance_type,
                            region,
                        )
                        if part
                    ),
                    observed_at=observed_at,
                    gpu_raw_name=gpu_name,
                    gpu_model=gpu_model,
                    gpu_count=gpu_count,
                    vram_gb=vram_gb,
                    price_usd_hr=hourly_cents / 100,
                    available_gpu_count=gpu_count,
                    country=None,
                    region=display_name or region or None,
                    is_spot=False,
                    is_secure=None,
                    availability_status="available",
                    raw_ref=raw_ref,
                    metadata={
                        "upstream_provider": cloud,
                        "cloud_instance_type": cloud_instance_type,
                        "shade_instance_type": shade_instance_type,
                        "region_code": region,
                        "deployment_type": entry.get("deployment_type"),
                        "interconnect": configuration.get("interconnect"),
                        "nvlink": configuration.get("nvlink"),
                        "price_basis": "shadeform_instance_hour",
                        "capacity_basis": "available_region_bundle_lower_bound",
                    },
                )
            )

    return normalized, sorted(set(unknown_gpu_names))


def _extract_instance_types(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, Mapping) and isinstance(payload.get("instance_types"), list):
        return [
            dict(row) for row in payload["instance_types"] if isinstance(row, Mapping)
        ]
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


def _provider_id(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    return PROVIDER_ALIASES.get(normalized, normalized) or "shadeform"
