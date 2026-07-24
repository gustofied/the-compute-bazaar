"""Hyperstack real-time GPU stock joined to its current pricebook."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests

from ..normalize import canonical_gpu_model
from ..schemas import GpuOffer
from .http import retrying_session


DEFAULT_HYPERSTACK_API_BASE = "https://infrahub-api.nexgencloud.com/v1"


@dataclass(frozen=True)
class HyperstackFetch:
    raw_payload: dict[str, Any]
    stocks: list[dict[str, Any]]
    pricebook: list[dict[str, Any]]


class HyperstackClient:
    def __init__(
        self,
        *,
        api_key: str,
        api_base: str = DEFAULT_HYPERSTACK_API_BASE,
        session: requests.Session | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("Hyperstack API key is required")
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.session = session or retrying_session()

    def fetch_stock_and_prices(self) -> HyperstackFetch:
        stocks_payload = self._get_json("/core/stocks")
        pricebook_payload = self._get_json("/pricebook")
        stocks = _extract_stocks(stocks_payload)
        pricebook = _extract_pricebook(pricebook_payload)
        return HyperstackFetch(
            raw_payload={
                "mode": "authenticated_live_stock_and_pricebook",
                "stocks_url": f"{self.api_base}/core/stocks",
                "pricebook_url": f"{self.api_base}/pricebook",
                "stocks_payload": stocks_payload,
                "pricebook_payload": pricebook_payload,
                "stock_region_count": len(stocks),
                "pricebook_entry_count": len(pricebook),
            },
            stocks=stocks,
            pricebook=pricebook,
        )

    def _get_json(self, path: str) -> Any:
        response = self.session.get(
            f"{self.api_base}{path}",
            params={},
            headers={"Accept": "application/json", "api_key": self.api_key},
            timeout=60,
        )
        response.raise_for_status()
        return response.json()


def normalize_stock(
    stocks: Iterable[Mapping[str, Any]],
    *,
    pricebook: Iterable[Mapping[str, Any]],
    observed_at: datetime,
    raw_ref: str | None,
) -> tuple[list[GpuOffer], list[str]]:
    prices = {
        _price_key(entry.get("name")): _float_or_none(entry.get("value"))
        for entry in pricebook
    }
    component_pricing = any((prices.get(name) or 0) > 0 for name in ("CPU", "RAM"))
    normalized: list[GpuOffer] = []
    unknown_gpu_names: list[str] = []

    for stock in stocks:
        region = str(stock.get("region") or "")
        models = stock.get("models") if isinstance(stock.get("models"), list) else []
        for model in models:
            if not isinstance(model, Mapping):
                continue
            gpu_name = str(model.get("model") or "")
            gpu_model = canonical_gpu_model(gpu_name)
            if not gpu_model:
                if gpu_name:
                    unknown_gpu_names.append(gpu_name)
                continue
            price_per_gpu = prices.get(_price_key(gpu_name))
            if price_per_gpu is None or price_per_gpu <= 0:
                continue

            configurations = (
                model.get("configurations")
                if isinstance(model.get("configurations"), Mapping)
                else {}
            )
            available_configurations = [
                (gpu_count, count)
                for key, value in configurations.items()
                if (gpu_count := _configuration_gpu_count(key)) is not None
                and (count := _int_or_none(value)) is not None
                and count > 0
            ]
            if not available_configurations:
                continue

            capacity_lower_bound = max(
                gpu_count * count for gpu_count, count in available_configurations
            )
            is_spot = gpu_name.lower().endswith("spot")
            for index, (gpu_count, configuration_count) in enumerate(
                sorted(available_configurations)
            ):
                model_id = gpu_model if gpu_count == 1 else f"{gpu_model}_x{gpu_count}"
                if component_pricing:
                    availability_status = "available_component_rate"
                else:
                    availability_status = "spot_available" if is_spot else "available"
                normalized.append(
                    GpuOffer(
                        provider="hyperstack",
                        source_offer_id=f"{region}:{gpu_name}:{gpu_count}x",
                        observed_at=observed_at,
                        gpu_raw_name=gpu_name,
                        gpu_model=model_id,
                        gpu_count=gpu_count,
                        vram_gb=_vram_from_model(gpu_name),
                        price_usd_hr=price_per_gpu * gpu_count,
                        available_gpu_count=(capacity_lower_bound if index == 0 else 0),
                        country=None,
                        region=region or None,
                        is_spot=is_spot,
                        is_secure=True,
                        availability_status=availability_status,
                        raw_ref=raw_ref,
                        metadata={
                            "available_label": model.get("available"),
                            "configuration_count": configuration_count,
                            "configurations": dict(configurations),
                            "planned_7_days": model.get("planned_7_days"),
                            "planned_30_days": model.get("planned_30_days"),
                            "planned_100_days": model.get("planned_100_days"),
                            "price_basis": "hyperstack_gpu_resource_hour",
                            "price_excludes": (
                                ["vcpu", "ram"] if component_pricing else []
                            ),
                            "capacity_basis": (
                                "max_deployable_configuration_gpu_units"
                            ),
                        },
                    )
                )

    return normalized, sorted(set(unknown_gpu_names))


def _extract_stocks(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, Mapping) or not isinstance(payload.get("stocks"), list):
        return []
    return [dict(row) for row in payload["stocks"] if isinstance(row, Mapping)]


def _extract_pricebook(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        return []
    return [dict(row) for row in payload if isinstance(row, Mapping)]


def _price_key(value: Any) -> str:
    return str(value or "").strip().upper()


def _configuration_gpu_count(value: Any) -> int | None:
    text = str(value or "").strip().lower()
    if not text.endswith("x"):
        return None
    return _int_or_none(text[:-1])


def _vram_from_model(value: str) -> float | None:
    import re

    match = re.search(r"(\d+)\s*G(?:B)?", value, flags=re.IGNORECASE)
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
