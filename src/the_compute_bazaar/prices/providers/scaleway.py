"""Scaleway public GPU prices and zone availability adapter."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests

from ..normalize import canonical_gpu_model
from ..schemas import GpuOffer
from .ecb import DEFAULT_ECB_EUR_USD_URL, fetch_latest_eur_usd_rate
from .http import retrying_session


DEFAULT_SCALEWAY_API_BASE = "https://api.scaleway.com"
DEFAULT_ECB_FX_URL = DEFAULT_ECB_EUR_USD_URL
DEFAULT_SCALEWAY_ZONES = (
    "fr-par-1",
    "fr-par-2",
    "fr-par-3",
    "nl-ams-1",
    "nl-ams-2",
    "nl-ams-3",
    "pl-waw-1",
    "pl-waw-2",
    "pl-waw-3",
    "it-mil-1",
)


@dataclass(frozen=True)
class ScalewayCatalogFetch:
    raw_payload: dict[str, Any]
    products: list[dict[str, Any]]
    eur_usd_rate: float
    fx_observed_date: str


class ScalewayClient:
    def __init__(
        self,
        *,
        api_base: str = DEFAULT_SCALEWAY_API_BASE,
        fx_url: str = DEFAULT_ECB_FX_URL,
        zones: Iterable[str] = DEFAULT_SCALEWAY_ZONES,
        session: requests.Session | None = None,
    ) -> None:
        self.api_base = api_base.rstrip("/")
        self.fx_url = fx_url
        self.zones = tuple(dict.fromkeys(zones))
        self.session = session or retrying_session()

    def fetch_gpu_catalog(self) -> ScalewayCatalogFetch:
        fx = fetch_latest_eur_usd_rate(self.session, fx_url=self.fx_url)
        zone_payloads: dict[str, Any] = {}
        products: list[dict[str, Any]] = []

        for zone in self.zones:
            types_payload = self._get(
                f"/instance/v1/zones/{zone}/products/servers",
                params={"per_page": 100},
            )
            availability_payload = self._get(
                f"/instance/v1/zones/{zone}/products/servers/availability",
                params={"per_page": 100},
            )
            zone_payloads[zone] = {
                "types": types_payload,
                "availability": availability_payload,
            }
            products.extend(
                _extract_gpu_products(
                    zone=zone,
                    types_payload=types_payload,
                    availability_payload=availability_payload,
                )
            )

        return ScalewayCatalogFetch(
            raw_payload={
                "mode": "public_zone_gpu_prices_and_availability",
                "api_base": self.api_base,
                "zones": list(self.zones),
                "zone_payloads": zone_payloads,
                "gpu_product_count": len(products),
                "fx": {
                    "source": "ecb_reference_rate",
                    "source_url": self.fx_url,
                    "currency_pair": "EUR/USD",
                    "observed_date": fx.observed_date,
                    "rate": fx.rate,
                    "payload": fx.raw_payload,
                },
            },
            products=products,
            eur_usd_rate=fx.rate,
            fx_observed_date=fx.observed_date,
        )

    def _get(self, path: str, *, params: dict[str, Any]) -> Any:
        response = self.session.get(
            f"{self.api_base}{path}",
            params=params,
            headers={
                "Accept": "application/json",
                "User-Agent": "the-compute-bazaar/0.1",
            },
            timeout=60,
        )
        response.raise_for_status()
        return response.json()


def normalize_gpu_products(
    products: Iterable[Mapping[str, Any]],
    *,
    eur_usd_rate: float,
    fx_observed_date: str,
    observed_at: datetime,
    raw_ref: str | None,
) -> tuple[list[GpuOffer], list[str]]:
    normalized: list[GpuOffer] = []
    unknown_gpu_names: list[str] = []

    for product in products:
        offer_id = str(product.get("offer_id") or "").strip()
        gpu_name = str(product.get("gpu_name") or "").strip()
        gpu_count = _int_or_none(product.get("gpu_count"))
        price_eur_hr = _float_or_none(product.get("hourly_price_eur"))
        if (
            not offer_id
            or not gpu_name
            or gpu_count is None
            or gpu_count <= 0
            or price_eur_hr is None
            or price_eur_hr <= 0
        ):
            continue

        vram_bytes = _float_or_none(product.get("gpu_memory_bytes"))
        vram_gb = vram_bytes / (1024**3) if vram_bytes else None
        gpu_model = canonical_gpu_model(
            gpu_name,
            vram_gb * 1024 if vram_gb is not None else None,
        )
        if not gpu_model:
            unknown_gpu_names.append(gpu_name)
            continue
        if gpu_count > 1:
            gpu_model = f"{gpu_model}_x{gpu_count}"

        zone = str(product.get("zone") or "").strip()
        source_availability = str(product.get("availability") or "").lower()
        is_deployable = source_availability in {"available", "scarce"}
        normalized.append(
            GpuOffer(
                provider="scaleway",
                source_connector="scaleway",
                source_offer_id=f"{offer_id}:{zone}",
                observed_at=observed_at,
                gpu_raw_name=gpu_name,
                gpu_model=gpu_model,
                gpu_count=gpu_count,
                vram_gb=vram_gb,
                price_usd_hr=price_eur_hr * eur_usd_rate,
                available_gpu_count=gpu_count if is_deployable else None,
                currency="USD",
                country=_country_for_zone(zone),
                region=zone or None,
                is_spot=False,
                is_secure=True,
                availability_status="available" if is_deployable else "unavailable",
                raw_ref=raw_ref,
                metadata={
                    "offer_id": offer_id,
                    "source_availability": source_availability,
                    "price_eur_instance_hr": price_eur_hr,
                    "eur_usd_rate": eur_usd_rate,
                    "fx_observed_date": fx_observed_date,
                    "price_basis": "scaleway_current_on_demand_instance_hour",
                    "capacity_basis": (
                        "zone_type_deployability_lower_bound"
                        if is_deployable
                        else None
                    ),
                    "vcpu_count": product.get("vcpu_count"),
                    "ram_bytes": product.get("ram_bytes"),
                    "end_of_service": product.get("end_of_service"),
                },
            )
        )

    return normalized, sorted(set(unknown_gpu_names))


def _extract_gpu_products(
    *,
    zone: str,
    types_payload: Any,
    availability_payload: Any,
) -> list[dict[str, Any]]:
    if not isinstance(types_payload, Mapping) or not isinstance(
        types_payload.get("servers"), Mapping
    ):
        return []
    availability = (
        availability_payload.get("servers")
        if isinstance(availability_payload, Mapping)
        and isinstance(availability_payload.get("servers"), Mapping)
        else {}
    )
    products: list[dict[str, Any]] = []
    for offer_id, raw_product in types_payload["servers"].items():
        if not isinstance(raw_product, Mapping):
            continue
        gpu_info = (
            raw_product.get("gpu_info")
            if isinstance(raw_product.get("gpu_info"), Mapping)
            else {}
        )
        gpu_count = _int_or_none(raw_product.get("gpu"))
        gpu_name = str(gpu_info.get("gpu_name") or "").strip()
        if not gpu_name or gpu_count is None or gpu_count <= 0:
            continue
        availability_entry = (
            availability.get(offer_id)
            if isinstance(availability.get(offer_id), Mapping)
            else {}
        )
        products.append(
            {
                "offer_id": str(offer_id),
                "zone": zone,
                "availability": availability_entry.get("availability"),
                "gpu_name": gpu_name,
                "gpu_count": gpu_count,
                "gpu_memory_bytes": gpu_info.get("gpu_memory"),
                "hourly_price_eur": raw_product.get("hourly_price"),
                "monthly_price_eur": raw_product.get("monthly_price"),
                "vcpu_count": raw_product.get("ncpus"),
                "ram_bytes": raw_product.get("ram"),
                "end_of_service": raw_product.get("end_of_service"),
            }
        )
    return products


def _country_for_zone(zone: str) -> str | None:
    return {
        "fr": "FR",
        "nl": "NL",
        "pl": "PL",
        "it": "IT",
    }.get(zone.split("-", 1)[0])


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
