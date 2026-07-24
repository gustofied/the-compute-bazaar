"""Oracle Cloud public GPU list-price adapter."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests

from ..normalize import canonical_gpu_model
from ..schemas import GpuOffer
from .http import retrying_session


DEFAULT_ORACLE_PRICE_API = (
    "https://apexapps.oracle.com/pls/apex/cetools/api/v1/products/"
)


@dataclass(frozen=True)
class OracleGpuSku:
    part_number: str
    gpu_name: str
    vram_gb: float
    package_model: str | None = None


DEFAULT_ORACLE_GPU_SKUS = (
    OracleGpuSku("B98415", "NVIDIA H100", 80),
    OracleGpuSku("B110519", "NVIDIA H200", 141),
    OracleGpuSku("B110978", "NVIDIA B200", 180),
    OracleGpuSku("B112237", "NVIDIA B300", 288),
    OracleGpuSku("B110979", "NVIDIA B200", 180, "GB200"),
    OracleGpuSku("B112140", "NVIDIA B300", 288, "GB300"),
)


@dataclass(frozen=True)
class OracleCatalogFetch:
    raw_payload: dict[str, Any]
    products: list[dict[str, Any]]


class OracleCloudClient:
    def __init__(
        self,
        *,
        api_url: str = DEFAULT_ORACLE_PRICE_API,
        skus: Iterable[OracleGpuSku] = DEFAULT_ORACLE_GPU_SKUS,
        session: requests.Session | None = None,
    ) -> None:
        self.api_url = api_url
        self.skus = tuple(skus)
        self.session = session or retrying_session()

    def fetch_gpu_catalog(self) -> OracleCatalogFetch:
        responses: dict[str, Any] = {}
        products: list[dict[str, Any]] = []
        for sku in self.skus:
            payload = self._get_product(sku.part_number)
            responses[sku.part_number] = payload
            items = payload.get("items") if isinstance(payload, Mapping) else None
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, Mapping):
                    continue
                products.append(
                    {
                        **dict(item),
                        "catalog_last_updated": payload.get("lastUpdated"),
                        "gpu_name": sku.gpu_name,
                        "vram_gb": sku.vram_gb,
                        "package_model": sku.package_model,
                    }
                )

        return OracleCatalogFetch(
            raw_payload={
                "mode": "oracle_public_gpu_list_prices",
                "api_url": self.api_url,
                "part_numbers": [sku.part_number for sku in self.skus],
                "responses": responses,
            },
            products=products,
        )

    def _get_product(self, part_number: str) -> Any:
        response = self.session.get(
            self.api_url,
            params={"partNumber": part_number, "currencyCode": "USD"},
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
    observed_at: datetime,
    raw_ref: str | None,
) -> tuple[list[GpuOffer], list[str]]:
    normalized: list[GpuOffer] = []
    unknown_gpu_names: list[str] = []

    for product in products:
        part_number = str(product.get("partNumber") or "").strip()
        gpu_name = str(product.get("gpu_name") or "").strip()
        vram_gb = _float_or_none(product.get("vram_gb"))
        price_usd_gpu_hr = _payg_usd_price(product)
        metric_name = str(product.get("metricName") or "").strip()
        if (
            not part_number
            or not gpu_name
            or vram_gb is None
            or price_usd_gpu_hr is None
            or price_usd_gpu_hr <= 0
            or metric_name.lower() != "gpu per hour"
        ):
            continue

        gpu_model = canonical_gpu_model(gpu_name, vram_gb * 1024)
        if not gpu_model:
            unknown_gpu_names.append(gpu_name)
            continue

        package_model = str(product.get("package_model") or "").strip() or None
        normalized.append(
            GpuOffer(
                provider="oracle_cloud",
                source_connector="oracle_cloud",
                source_offer_id=part_number,
                observed_at=observed_at,
                gpu_raw_name=gpu_name,
                gpu_model=gpu_model,
                gpu_count=1,
                vram_gb=vram_gb,
                price_usd_hr=price_usd_gpu_hr,
                currency="USD",
                is_spot=False,
                availability_status="published_rate",
                raw_ref=raw_ref,
                metadata={
                    "part_number": part_number,
                    "display_name": product.get("displayName"),
                    "metric_name": metric_name,
                    "service_category": product.get("serviceCategory"),
                    "pricing_model": "PAY_AS_YOU_GO",
                    "price_basis": "oracle_public_payg_gpu_hour",
                    "catalog_last_updated": product.get("catalog_last_updated"),
                    "package_model": package_model,
                    "capacity_basis": None,
                },
            )
        )

    return normalized, sorted(set(unknown_gpu_names))


def _payg_usd_price(product: Mapping[str, Any]) -> float | None:
    localizations = product.get("currencyCodeLocalizations")
    if not isinstance(localizations, list):
        localizations = product.get("prices")
    if not isinstance(localizations, list):
        return None

    for localization in localizations:
        if not isinstance(localization, Mapping):
            continue
        if str(localization.get("currencyCode") or "").upper() != "USD":
            continue
        prices = localization.get("prices")
        if not isinstance(prices, list):
            continue
        for price in prices:
            if not isinstance(price, Mapping):
                continue
            if str(price.get("model") or "").upper() != "PAY_AS_YOU_GO":
                continue
            return _float_or_none(price.get("value"))
    return None


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
