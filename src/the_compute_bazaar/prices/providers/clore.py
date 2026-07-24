"""Clore.ai public live GPU marketplace adapter."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests

from ..normalize import canonical_gpu_model
from ..schemas import GpuOffer


DEFAULT_CLORE_MARKETPLACE_URL = "https://api.clore.ai/v1/marketplace"


@dataclass(frozen=True)
class CloreMarketplaceFetch:
    raw_payload: dict[str, Any]
    servers: list[dict[str, Any]]


class CloreClient:
    def __init__(
        self,
        *,
        marketplace_url: str = DEFAULT_CLORE_MARKETPLACE_URL,
        session: requests.Session | None = None,
    ) -> None:
        self.marketplace_url = marketplace_url
        self.session = session or requests.Session()

    def fetch_marketplace(self) -> CloreMarketplaceFetch:
        response = self.session.get(
            self.marketplace_url,
            params={},
            headers={"Accept": "application/json"},
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, Mapping):
            raise RuntimeError("Clore marketplace returned a non-object response")
        if payload.get("code") not in {None, 0}:
            raise RuntimeError(
                f"Clore marketplace returned code {payload.get('code')}: "
                f"{payload.get('error') or 'unknown error'}"
            )

        raw_servers = payload.get("servers")
        servers = (
            [dict(server) for server in raw_servers if isinstance(server, Mapping)]
            if isinstance(raw_servers, list)
            else []
        )
        return CloreMarketplaceFetch(
            raw_payload={
                "mode": "public_live_marketplace",
                "source_url": self.marketplace_url,
                "server_count": len(servers),
                "payload": dict(payload),
            },
            servers=servers,
        )


def normalize_servers(
    servers: Iterable[Mapping[str, Any]],
    *,
    observed_at: datetime,
    raw_ref: str | None,
) -> tuple[list[GpuOffer], list[str]]:
    normalized: list[GpuOffer] = []
    unknown_gpu_names: list[str] = []

    for server in servers:
        if server.get("rented") is not False:
            continue

        specs = server.get("specs") if isinstance(server.get("specs"), Mapping) else {}
        gpu_array = (
            server.get("gpu_array") if isinstance(server.get("gpu_array"), list) else []
        )
        gpu_names = [str(value).strip() for value in gpu_array if str(value).strip()]
        gpu_name = gpu_names[0] if gpu_names else _gpu_name_from_specs(specs.get("gpu"))
        gpu_count = len(gpu_names) or _gpu_count_from_specs(specs.get("gpu"))
        vram_gb = _float_or_none(specs.get("gpuram"))
        gpu_model = canonical_gpu_model(gpu_name, vram_gb * 1024 if vram_gb else None)
        if not gpu_model:
            raw_gpu = str(specs.get("gpu") or gpu_name).strip()
            if raw_gpu:
                unknown_gpu_names.append(raw_gpu)
            continue

        price = server.get("price") if isinstance(server.get("price"), Mapping) else {}
        usd = price.get("usd") if isinstance(price.get("usd"), Mapping) else {}
        instance_price = _float_or_none(usd.get("on_demand_usd"))
        if instance_price is None or instance_price <= 0 or gpu_count <= 0:
            continue
        if gpu_count > 1:
            gpu_model = f"{gpu_model}_x{gpu_count}"

        network = specs.get("net") if isinstance(specs.get("net"), Mapping) else {}
        rating = (
            server.get("rating") if isinstance(server.get("rating"), Mapping) else {}
        )
        partial_rental = server.get("partial_gpu_rental")
        partial_rental_details = (
            partial_rental if isinstance(partial_rental, Mapping) else {}
        )
        partial_available = _int_or_none(partial_rental_details.get("available_gpus"))
        available_gpu_count = (
            partial_available
            if partial_available is not None and partial_available > 0
            else gpu_count
        )
        normalized.append(
            GpuOffer(
                provider="clore",
                source_offer_id=f"server:{server.get('id')}:ondemand",
                observed_at=observed_at,
                gpu_raw_name=str(specs.get("gpu") or gpu_name),
                gpu_model=gpu_model,
                gpu_count=gpu_count,
                vram_gb=vram_gb,
                price_usd_hr=instance_price,
                available_gpu_count=available_gpu_count,
                country=str(network.get("cc") or "") or None,
                region=None,
                is_spot=False,
                is_secure=None,
                availability_status="available",
                raw_ref=raw_ref,
                metadata={
                    "server_id": server.get("id"),
                    "owner_id": server.get("owner"),
                    "reliability": server.get("reliability"),
                    "rating_average": rating.get("avg"),
                    "rating_count": rating.get("cnt"),
                    "partial_gpu_rental_enabled": bool(partial_rental),
                    "partial_gpu_total": partial_rental_details.get("total_gpus"),
                    "partial_gpu_available": partial_rental_details.get(
                        "available_gpus"
                    ),
                    "cuda_version": server.get("cuda_version"),
                    "minimum_rental_length": server.get("mrl"),
                    "network_download_mbps": network.get("down"),
                    "network_upload_mbps": network.get("up"),
                    "capacity_confirmed": True,
                    "price_basis": "clore_server_on_demand_hour",
                    "price_source_field": "price.usd.on_demand_usd",
                    "capacity_basis": (
                        "partial_gpu_available"
                        if partial_available is not None and partial_available > 0
                        else "available_server_bundle"
                    ),
                },
            )
        )

    return normalized, sorted(set(unknown_gpu_names))


def _gpu_name_from_specs(value: Any) -> str:
    text = str(value or "").strip()
    if "x " in text.lower():
        return text.split(" ", 1)[1]
    return text


def _gpu_count_from_specs(value: Any) -> int:
    text = str(value or "").strip()
    prefix = text.lower().split("x ", 1)[0]
    try:
        return int(prefix)
    except (TypeError, ValueError):
        return 1 if text else 0


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
