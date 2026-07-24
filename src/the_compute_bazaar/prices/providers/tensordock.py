"""TensorDock live hostnode stock and GPU component pricing."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests

from ..normalize import canonical_gpu_model
from ..schemas import GpuOffer
from .http import retrying_session


DEFAULT_TENSORDOCK_API_BASE = "https://dashboard.tensordock.com/api/v2"


@dataclass(frozen=True)
class TensorDockFetch:
    raw_payload: dict[str, Any]
    hostnodes: list[dict[str, Any]]


class TensorDockClient:
    def __init__(
        self,
        *,
        api_key: str,
        api_base: str = DEFAULT_TENSORDOCK_API_BASE,
        session: requests.Session | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("TensorDock API key is required")
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.session = session or retrying_session()

    def fetch_hostnodes(self) -> TensorDockFetch:
        response = self.session.get(
            f"{self.api_base}/hostnodes",
            params={},
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        hostnodes = _extract_hostnodes(payload)
        return TensorDockFetch(
            raw_payload={
                "mode": "authenticated_live_hostnodes",
                "source_url": f"{self.api_base}/hostnodes",
                "payload": payload,
                "hostnode_count": len(hostnodes),
                "hostnodes": hostnodes,
            },
            hostnodes=hostnodes,
        )


def normalize_hostnodes(
    hostnodes: Iterable[Mapping[str, Any]],
    *,
    observed_at: datetime,
    raw_ref: str | None,
) -> tuple[list[GpuOffer], list[str]]:
    normalized: list[GpuOffer] = []
    unknown_gpu_names: list[str] = []

    for hostnode in hostnodes:
        resources = (
            hostnode.get("available_resources")
            if isinstance(hostnode.get("available_resources"), Mapping)
            else {}
        )
        gpus = resources.get("gpus") if isinstance(resources.get("gpus"), list) else []
        location = (
            hostnode.get("location")
            if isinstance(hostnode.get("location"), Mapping)
            else {}
        )
        hostnode_id = str(hostnode.get("id") or "")
        region = (
            ", ".join(
                str(value).strip()
                for value in (
                    location.get("city"),
                    location.get("stateprovince"),
                )
                if str(value or "").strip()
            )
            or None
        )

        for gpu in gpus:
            if not isinstance(gpu, Mapping):
                continue
            gpu_name = str(
                gpu.get("displayName")
                or gpu.get("display_name")
                or gpu.get("v0Name")
                or ""
            )
            gpu_model = canonical_gpu_model(gpu_name)
            if not gpu_model:
                if gpu_name:
                    unknown_gpu_names.append(gpu_name)
                continue
            price = _float_or_none(gpu.get("price_per_hr"))
            available_count = _int_or_none(
                gpu.get("availableCount") or gpu.get("max_count")
            )
            if price is None or price <= 0:
                continue
            is_available = available_count is not None and available_count > 0
            gpu_key = str(gpu.get("v0Name") or gpu_name)
            normalized.append(
                GpuOffer(
                    provider="tensordock",
                    source_offer_id=f"{hostnode_id}:{gpu_key}",
                    observed_at=observed_at,
                    gpu_raw_name=gpu_name,
                    gpu_model=gpu_model,
                    gpu_count=1,
                    vram_gb=_vram_from_name(gpu_name),
                    price_usd_hr=price,
                    available_gpu_count=available_count if is_available else None,
                    country=_string_or_none(location.get("country")),
                    region=region,
                    is_spot=False,
                    is_secure=None,
                    availability_status=(
                        "available_component_rate"
                        if is_available
                        else "unavailable_component_rate"
                    ),
                    raw_ref=raw_ref,
                    metadata={
                        "hostnode_id": hostnode_id,
                        "location_id": hostnode.get("location_id"),
                        "organization_name": location.get("organizationName"),
                        "uptime_percentage": hostnode.get("uptime_percentage"),
                        "gpu_key": gpu_key,
                        "price_basis": "tensordock_gpu_component_hour",
                        "price_excludes": ["vcpu", "ram", "storage"],
                        "capacity_basis": "provider_available_count",
                    },
                )
            )

    return normalized, sorted(set(unknown_gpu_names))


def _extract_hostnodes(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, Mapping):
        return []
    data = payload.get("data")
    if not isinstance(data, Mapping):
        return []
    hostnodes = data.get("hostnodes")
    if not isinstance(hostnodes, list):
        return []
    return [dict(row) for row in hostnodes if isinstance(row, Mapping)]


def _vram_from_name(value: str) -> float | None:
    import re

    match = re.search(r"(\d+(?:\.\d+)?)\s*gb", value, flags=re.IGNORECASE)
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


def _string_or_none(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None
