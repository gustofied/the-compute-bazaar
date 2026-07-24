"""Verda public GPU catalog and authenticated live availability adapter."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests

from ..normalize import canonical_gpu_model
from ..schemas import GpuOffer


DEFAULT_VERDA_API_BASE = "https://api.verda.com/v1"


@dataclass(frozen=True)
class VerdaCatalogFetch:
    raw_payload: dict[str, Any]
    instance_types: list[dict[str, Any]]
    availability: list[dict[str, Any]] | None


class VerdaClient:
    def __init__(
        self,
        *,
        client_id: str | None = None,
        client_secret: str | None = None,
        access_token: str | None = None,
        api_base: str = DEFAULT_VERDA_API_BASE,
        session: requests.Session | None = None,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token = access_token
        self.api_base = api_base.rstrip("/")
        self.session = session or requests.Session()

    def fetch_catalog(self) -> VerdaCatalogFetch:
        instance_types_payload = self._get_json("/instance-types", authenticated=False)
        instance_types = _mapping_rows(instance_types_payload)

        availability: list[dict[str, Any]] | None = None
        token = self.access_token or self._fetch_access_token()
        if token:
            availability = _mapping_rows(
                self._get_json(
                    "/instance-availability", authenticated=True, token=token
                )
            )

        return VerdaCatalogFetch(
            raw_payload={
                "mode": (
                    "public_catalog_with_live_availability"
                    if availability is not None
                    else "public_catalog"
                ),
                "source_url": f"{self.api_base}/instance-types",
                "availability_source_url": (
                    f"{self.api_base}/instance-availability"
                    if availability is not None
                    else None
                ),
                "instance_type_count": len(instance_types),
                "availability_location_count": len(availability or []),
                "instance_types": instance_types,
                "availability": availability,
            },
            instance_types=instance_types,
            availability=availability,
        )

    def _fetch_access_token(self) -> str | None:
        if not self.client_id or not self.client_secret:
            return None
        response = self.session.post(
            f"{self.api_base}/oauth2/token",
            json={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, Mapping) or not payload.get("access_token"):
            raise RuntimeError("Verda OAuth response did not contain an access token")
        return str(payload["access_token"])

    def _get_json(
        self,
        path: str,
        *,
        authenticated: bool,
        token: str | None = None,
    ) -> Any:
        headers = {"Accept": "application/json"}
        if authenticated:
            if not token:
                raise RuntimeError("Verda availability requires an access token")
            headers["Authorization"] = f"Bearer {token}"
        response = self.session.get(
            f"{self.api_base}{path}",
            params={},
            headers=headers,
            timeout=60,
        )
        response.raise_for_status()
        return response.json()


def normalize_instance_catalog(
    instance_types: Iterable[Mapping[str, Any]],
    *,
    availability: Iterable[Mapping[str, Any]] | None,
    observed_at: datetime,
    raw_ref: str | None,
) -> tuple[list[GpuOffer], list[str]]:
    normalized: list[GpuOffer] = []
    unknown_gpu_names: list[str] = []
    locations_by_type = _locations_by_instance_type(availability)
    has_live_availability = availability is not None

    for entry in instance_types:
        gpu_name = str(
            entry.get("name") or entry.get("display_name") or entry.get("model") or ""
        )
        gpu = entry.get("gpu") if isinstance(entry.get("gpu"), Mapping) else {}
        gpu_memory = (
            entry.get("gpu_memory")
            if isinstance(entry.get("gpu_memory"), Mapping)
            else {}
        )
        gpu_count = _int_or_none(gpu.get("number_of_gpus")) or 1
        vram_gb = _float_or_none(
            gpu_memory.get("size_in_gigabytes")
        ) or _vram_from_name(gpu_name)
        gpu_model = canonical_gpu_model(gpu_name, vram_gb * 1024 if vram_gb else None)
        if not gpu_model:
            if gpu_name:
                unknown_gpu_names.append(gpu_name)
            continue
        if gpu_count > 1:
            gpu_model = f"{gpu_model}_x{gpu_count}"

        currency = str(entry.get("currency") or "").upper()
        instance_type = str(entry.get("instance_type") or entry.get("id") or "")
        if currency != "USD" or not instance_type:
            continue

        on_demand_price = _float_or_none(entry.get("price_per_hour"))
        if on_demand_price is not None and on_demand_price > 0:
            live_locations = locations_by_type.get(instance_type, [])
            if has_live_availability and live_locations:
                for location in live_locations:
                    normalized.append(
                        _offer(
                            entry=entry,
                            instance_type=instance_type,
                            gpu_name=gpu_name,
                            gpu_model=gpu_model,
                            gpu_count=gpu_count,
                            vram_gb=vram_gb,
                            price=on_demand_price,
                            observed_at=observed_at,
                            raw_ref=raw_ref,
                            region=location,
                            is_spot=False,
                            availability_status="available",
                            capacity_confirmed=True,
                        )
                    )
            else:
                normalized.append(
                    _offer(
                        entry=entry,
                        instance_type=instance_type,
                        gpu_name=gpu_name,
                        gpu_model=gpu_model,
                        gpu_count=gpu_count,
                        vram_gb=vram_gb,
                        price=on_demand_price,
                        observed_at=observed_at,
                        raw_ref=raw_ref,
                        region="global",
                        is_spot=False,
                        availability_status=(
                            "unavailable" if has_live_availability else "published_rate"
                        ),
                        capacity_confirmed=False,
                    )
                )

        spot_price = _float_or_none(entry.get("spot_price"))
        if spot_price is not None and spot_price > 0:
            normalized.append(
                _offer(
                    entry=entry,
                    instance_type=instance_type,
                    gpu_name=gpu_name,
                    gpu_model=gpu_model,
                    gpu_count=gpu_count,
                    vram_gb=vram_gb,
                    price=spot_price,
                    observed_at=observed_at,
                    raw_ref=raw_ref,
                    region="global",
                    is_spot=True,
                    availability_status=(
                        "spot_price_observed"
                        if has_live_availability
                        else "published_rate_spot"
                    ),
                    capacity_confirmed=False,
                )
            )

    return normalized, sorted(set(unknown_gpu_names))


def _offer(
    *,
    entry: Mapping[str, Any],
    instance_type: str,
    gpu_name: str,
    gpu_model: str,
    gpu_count: int,
    vram_gb: float | None,
    price: float,
    observed_at: datetime,
    raw_ref: str | None,
    region: str,
    is_spot: bool,
    availability_status: str,
    capacity_confirmed: bool,
) -> GpuOffer:
    price_kind = "spot" if is_spot else "ondemand"
    return GpuOffer(
        provider="verda",
        source_offer_id=f"{instance_type}:{region}:{price_kind}",
        observed_at=observed_at,
        gpu_raw_name=gpu_name,
        gpu_model=gpu_model,
        gpu_count=gpu_count,
        vram_gb=vram_gb,
        price_usd_hr=price,
        available_gpu_count=gpu_count if capacity_confirmed else None,
        country=_country_from_location(region),
        region=region,
        is_spot=is_spot,
        is_secure=True,
        availability_status=availability_status,
        raw_ref=raw_ref,
        metadata={
            "instance_type": instance_type,
            "manufacturer": entry.get("manufacturer"),
            "gpu_description": (
                entry.get("gpu", {}).get("description")
                if isinstance(entry.get("gpu"), Mapping)
                else None
            ),
            "p2p": entry.get("p2p"),
            "capacity_confirmed": capacity_confirmed,
            "price_basis": (
                "verda_spot_instance_hour"
                if is_spot
                else "verda_on_demand_instance_hour"
            ),
            "capacity_basis": (
                "available_instance_type_location_lower_bound"
                if capacity_confirmed
                else None
            ),
        },
    )


def _locations_by_instance_type(
    availability: Iterable[Mapping[str, Any]] | None,
) -> dict[str, list[str]]:
    locations: dict[str, list[str]] = {}
    if availability is None:
        return locations
    for row in availability:
        location = str(row.get("location_code") or "")
        instance_types = row.get("availabilities")
        if not location or not isinstance(instance_types, list):
            continue
        for instance_type in instance_types:
            locations.setdefault(str(instance_type), []).append(location)
    return {key: sorted(set(values)) for key, values in locations.items()}


def _mapping_rows(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        return []
    return [dict(row) for row in payload if isinstance(row, Mapping)]


def _vram_from_name(value: str) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*GB", value, re.IGNORECASE)
    return float(match.group(1)) if match else None


def _country_from_location(location: str) -> str | None:
    if location == "global" or "-" not in location:
        return None
    return location.split("-", 1)[0]


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
