"""OVHcloud public GPU instance catalog adapter."""

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


DEFAULT_OVH_CATALOG_URL = "https://eu.api.ovh.com/v1/order/catalog/public/cloud"
DEFAULT_OVH_SUBSIDIARY = "FR"
OVH_PRICE_DIVISOR = 100_000_000


@dataclass(frozen=True)
class OvhCatalogFetch:
    raw_payload: dict[str, Any]
    plans: list[dict[str, Any]]
    eur_usd_rate: float
    fx_observed_date: str


class OvhCloudClient:
    def __init__(
        self,
        *,
        catalog_url: str = DEFAULT_OVH_CATALOG_URL,
        subsidiary: str = DEFAULT_OVH_SUBSIDIARY,
        fx_url: str = DEFAULT_ECB_EUR_USD_URL,
        session: requests.Session | None = None,
    ) -> None:
        self.catalog_url = catalog_url
        self.subsidiary = subsidiary
        self.fx_url = fx_url
        self.session = session or retrying_session()

    def fetch_gpu_catalog(self) -> OvhCatalogFetch:
        response = self.session.get(
            self.catalog_url,
            params={"ovhSubsidiary": self.subsidiary},
            headers={
                "Accept": "application/json",
                "User-Agent": "the-compute-bazaar/0.1",
            },
            timeout=90,
        )
        response.raise_for_status()
        payload = response.json()
        currency = _catalog_currency(payload)
        if currency != "EUR":
            raise ValueError(
                f"OVHcloud catalog currency must be EUR, received {currency or 'none'}"
            )
        plans = _extract_gpu_instance_plans(payload)
        fx = fetch_latest_eur_usd_rate(self.session, fx_url=self.fx_url)
        return OvhCatalogFetch(
            raw_payload={
                "mode": "ovhcloud_public_gpu_instance_catalog",
                "catalog_url": self.catalog_url,
                "subsidiary": self.subsidiary,
                "catalog_id": (
                    payload.get("catalogId") if isinstance(payload, Mapping) else None
                ),
                "locale": payload.get("locale") if isinstance(payload, Mapping) else None,
                "gpu_plan_count": len(plans),
                "plans": plans,
                "fx": {
                    "source": "ecb_reference_rate",
                    "source_url": self.fx_url,
                    "currency_pair": "EUR/USD",
                    "observed_date": fx.observed_date,
                    "rate": fx.rate,
                    "payload": fx.raw_payload,
                },
            },
            plans=plans,
            eur_usd_rate=fx.rate,
            fx_observed_date=fx.observed_date,
        )


def normalize_gpu_plans(
    plans: Iterable[Mapping[str, Any]],
    *,
    eur_usd_rate: float,
    fx_observed_date: str,
    observed_at: datetime,
    raw_ref: str | None,
) -> tuple[list[GpuOffer], list[str]]:
    normalized: list[GpuOffer] = []
    unknown_gpu_names: list[str] = []

    for plan in plans:
        plan_code = str(plan.get("planCode") or "").strip()
        technical = _mapping(_mapping(plan.get("blobs")).get("technical"))
        gpu = _mapping(technical.get("gpu"))
        memory = _mapping(gpu.get("memory"))
        gpu_name = str(gpu.get("model") or "").strip()
        gpu_count = _int_or_none(gpu.get("number"))
        vram_gb = _float_or_none(memory.get("size"))
        price_eur_hr = _hourly_price_eur(plan)
        if (
            not plan_code
            or not gpu_name
            or gpu_count is None
            or gpu_count <= 0
            or vram_gb is None
            or price_eur_hr is None
            or price_eur_hr <= 0
        ):
            continue

        gpu_model = canonical_gpu_model(gpu_name, vram_gb * 1024)
        if not gpu_model:
            unknown_gpu_names.append(gpu_name)
            continue
        if gpu_count > 1:
            gpu_model = f"{gpu_model}_x{gpu_count}"

        normalized.append(
            GpuOffer(
                provider="ovhcloud",
                source_connector="ovhcloud",
                source_offer_id=plan_code,
                observed_at=observed_at,
                gpu_raw_name=gpu_name,
                gpu_model=gpu_model,
                gpu_count=gpu_count,
                vram_gb=vram_gb,
                price_usd_hr=price_eur_hr * eur_usd_rate,
                currency="USD",
                is_spot=False,
                availability_status="published_rate",
                raw_ref=raw_ref,
                metadata={
                    "plan_code": plan_code,
                    "invoice_name": plan.get("invoiceName"),
                    "price_eur_instance_hr": price_eur_hr,
                    "eur_usd_rate": eur_usd_rate,
                    "fx_observed_date": fx_observed_date,
                    "price_basis": "ovhcloud_public_on_demand_instance_hour",
                    "capacity_basis": None,
                    "cpu_cores": _mapping(technical.get("cpu")).get("cores"),
                    "ram_gb": _mapping(technical.get("memory")).get("size"),
                    "active_tags": _mapping(plan.get("blobs")).get("tags"),
                },
            )
        )

    return normalized, sorted(set(unknown_gpu_names))


def _extract_gpu_instance_plans(payload: Any) -> list[dict[str, Any]]:
    plans: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in _walk_mappings(payload):
        plan_code = str(item.get("planCode") or "")
        blobs = _mapping(item.get("blobs"))
        commercial = _mapping(blobs.get("commercial"))
        technical = _mapping(blobs.get("technical"))
        if (
            not plan_code.endswith(".consumption")
            or item.get("product") != "publiccloud-instance"
            or item.get("pricingType") != "consumption"
            or commercial.get("brick") != "gpu"
            or not _mapping(technical.get("gpu"))
            or str(_mapping(technical.get("os")).get("family") or "").lower()
            != "linux"
            or plan_code in seen
        ):
            continue
        seen.add(plan_code)
        plans.append(dict(item))
    return sorted(plans, key=lambda row: str(row.get("planCode") or ""))


def _walk_mappings(value: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        yield value
        for nested in value.values():
            yield from _walk_mappings(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_mappings(nested)


def _catalog_currency(payload: Any) -> str:
    if not isinstance(payload, Mapping):
        return ""
    return str(_mapping(payload.get("locale")).get("currencyCode") or "").upper()


def _hourly_price_eur(plan: Mapping[str, Any]) -> float | None:
    pricings = plan.get("pricings")
    if not isinstance(pricings, list):
        return None
    for pricing in pricings:
        if not isinstance(pricing, Mapping):
            continue
        if (
            pricing.get("intervalUnit") != "hour"
            or _float_or_none(pricing.get("interval")) != 1
            or pricing.get("type") != "consumption"
        ):
            continue
        raw_price = _float_or_none(pricing.get("price"))
        if raw_price is not None:
            return raw_price / OVH_PRICE_DIVISOR
    return None


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


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
