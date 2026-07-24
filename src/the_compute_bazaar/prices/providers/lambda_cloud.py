"""Lambda Cloud live instance-type pricing and capacity regions."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests

from ..normalize import canonical_gpu_model
from ..schemas import GpuOffer
from .http import retrying_session


DEFAULT_LAMBDA_API_BASE = "https://cloud.lambda.ai/api/v1"


@dataclass(frozen=True)
class LambdaInstanceTypesFetch:
    raw_payload: dict[str, Any]
    instance_types: list[dict[str, Any]]


class LambdaCloudClient:
    def __init__(
        self,
        *,
        api_key: str,
        api_base: str = DEFAULT_LAMBDA_API_BASE,
        session: requests.Session | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("Lambda Cloud API key is required")
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.session = session or retrying_session()

    def fetch_instance_types(self) -> LambdaInstanceTypesFetch:
        response = self.session.get(
            f"{self.api_base}/instance-types",
            params={},
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        instance_types = _extract_instance_types(payload)
        return LambdaInstanceTypesFetch(
            raw_payload={
                "mode": "authenticated_live_instance_types",
                "source_url": f"{self.api_base}/instance-types",
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
        instance_type = (
            entry.get("instance_type")
            if isinstance(entry.get("instance_type"), Mapping)
            else {}
        )
        name = str(instance_type.get("name") or "")
        gpu_name = str(
            instance_type.get("gpu_description")
            or instance_type.get("description")
            or name
        )
        specs = (
            instance_type.get("specs")
            if isinstance(instance_type.get("specs"), Mapping)
            else {}
        )
        gpu_count = _int_or_none(specs.get("gpus")) or 1
        gpu_model = canonical_gpu_model(gpu_name)
        if not gpu_model:
            if gpu_name:
                unknown_gpu_names.append(gpu_name)
            continue
        if gpu_count > 1:
            gpu_model = f"{gpu_model}_x{gpu_count}"
        price_cents = _float_or_none(instance_type.get("price_cents_per_hour"))
        if price_cents is None or price_cents <= 0:
            continue

        regions = (
            entry.get("regions_with_capacity_available")
            if isinstance(entry.get("regions_with_capacity_available"), list)
            else []
        )
        for region_entry in regions:
            if not isinstance(region_entry, Mapping):
                continue
            region = str(region_entry.get("name") or "")
            normalized.append(
                GpuOffer(
                    provider="lambda",
                    source_offer_id=f"{name}:{region}",
                    observed_at=observed_at,
                    gpu_raw_name=gpu_name,
                    gpu_model=gpu_model,
                    gpu_count=gpu_count,
                    vram_gb=_vram_from_name(gpu_name),
                    price_usd_hr=price_cents / 100,
                    available_gpu_count=gpu_count,
                    country=None,
                    region=region or None,
                    is_spot=False,
                    is_secure=True,
                    availability_status="available",
                    raw_ref=raw_ref,
                    metadata={
                        "instance_type": name,
                        "description": instance_type.get("description"),
                        "region_description": region_entry.get("description"),
                        "vcpus": specs.get("vcpus"),
                        "memory_gib": specs.get("memory_gib"),
                        "storage_gib": specs.get("storage_gib"),
                        "price_basis": "lambda_instance_hour",
                        "capacity_basis": "available_region_bundle_lower_bound",
                    },
                )
            )

    return normalized, sorted(set(unknown_gpu_names))


def _extract_instance_types(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, Mapping):
        return []
    data = payload.get("data")
    if not isinstance(data, Mapping):
        return []
    return [dict(entry) for entry in data.values() if isinstance(entry, Mapping)]


def _vram_from_name(value: str) -> float | None:
    import re

    match = re.search(r"(\d+(?:\.\d+)?)\s*GB", value, flags=re.IGNORECASE)
    return float(match.group(1)) if match else None


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
