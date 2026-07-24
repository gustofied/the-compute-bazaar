"""Inference.sh public cross-cloud GPU instance catalog."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests

from ..normalize import canonical_gpu_model
from ..schemas import GpuOffer
from .http import retrying_session


DEFAULT_INFERENCE_SH_API_BASE = "https://api.inference.sh"
PROVIDER_ALIASES = {
    "lambdalabs": "lambda",
    "massedcompute": "massed_compute",
}


@dataclass(frozen=True)
class InferenceShInstanceTypesFetch:
    raw_payload: dict[str, Any]
    instance_types: list[dict[str, Any]]


class InferenceShClient:
    def __init__(
        self,
        *,
        api_base: str = DEFAULT_INFERENCE_SH_API_BASE,
        session: requests.Session | None = None,
    ) -> None:
        self.api_base = api_base.rstrip("/")
        self.session = session or retrying_session()

    def fetch_instance_types(self) -> InferenceShInstanceTypesFetch:
        response = self.session.get(
            f"{self.api_base}/instances/types",
            params={"available": "true"},
            headers={
                "Accept": "application/json",
                "X-API-Version": "2",
            },
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        instance_types = _extract_instance_types(payload)
        return InferenceShInstanceTypesFetch(
            raw_payload={
                "mode": "public_hourly_cached_available_catalog",
                "source_url": f"{self.api_base}/instances/types?available=true",
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
        gpu_name = str(
            configuration.get("gpu_type")
            or entry.get("shade_instance_type")
            or entry.get("cloud_instance_type")
            or ""
        )
        vram_gb = _float_or_none(configuration.get("vram_per_gpu_in_gb"))
        gpu_model = canonical_gpu_model(
            gpu_name,
            vram_gb * 1024 if vram_gb is not None else None,
        )
        if not gpu_model:
            if gpu_name:
                unknown_gpu_names.append(gpu_name)
            continue

        gpu_count = _int_or_none(configuration.get("num_gpus")) or 1
        if gpu_count > 1:
            gpu_model = f"{gpu_model}_x{gpu_count}"
        hourly_price_cents = _float_or_none(entry.get("hourly_price"))
        if hourly_price_cents is None or hourly_price_cents <= 0:
            continue

        cloud = str(entry.get("cloud") or "").strip().lower()
        provider = PROVIDER_ALIASES.get(cloud, cloud)
        if not provider:
            continue
        available_regions = _available_regions(entry)
        for region in available_regions:
            normalized.append(
                GpuOffer(
                    provider=provider,
                    source_connector="inference_sh",
                    source_offer_id=f"{entry.get('id') or entry.get('shade_instance_type')}:{region}",
                    observed_at=observed_at,
                    gpu_raw_name=gpu_name,
                    gpu_model=gpu_model,
                    gpu_count=gpu_count,
                    vram_gb=vram_gb,
                    price_usd_hr=hourly_price_cents / 100,
                    available_gpu_count=gpu_count,
                    country=None,
                    region=region,
                    is_spot=False,
                    is_secure=None,
                    availability_status="available",
                    raw_ref=raw_ref,
                    metadata={
                        "cloud": cloud,
                        "cloud_instance_type": entry.get("cloud_instance_type"),
                        "shade_instance_type": entry.get("shade_instance_type"),
                        "deployment_type": entry.get("deployment_type"),
                        "interconnect": configuration.get("interconnect"),
                        "nvlink": configuration.get("nvlink"),
                        "vcpus": configuration.get("vcpus"),
                        "memory_gb": configuration.get("memory_in_gb"),
                        "storage_gb": configuration.get("storage_in_gb"),
                        "price_basis": "inference_sh_instance_hour",
                        "capacity_basis": "available_region_bundle_lower_bound",
                        "catalog_cache_seconds": 3600,
                    },
                )
            )

    return normalized, sorted(set(unknown_gpu_names))


def _extract_instance_types(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [dict(row) for row in payload if isinstance(row, Mapping)]
    if isinstance(payload, Mapping) and isinstance(payload.get("data"), list):
        return [dict(row) for row in payload["data"] if isinstance(row, Mapping)]
    return []


def _available_regions(entry: Mapping[str, Any]) -> list[str]:
    availability = (
        entry.get("availability") if isinstance(entry.get("availability"), list) else []
    )
    regions = {
        str(row.get("region") or entry.get("region") or "global").strip()
        for row in availability
        if isinstance(row, Mapping) and row.get("available") is True
    }
    return sorted(region or "global" for region in regions)


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
