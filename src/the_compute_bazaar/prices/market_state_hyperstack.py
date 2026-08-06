"""Normalize Hyperstack stock observations."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from .normalize import canonical_gpu_model
from .schemas import ComputeMarketState

from .market_state_common import (
    _configuration_gpu_count,
    _float_or_none,
    _state,
)


HYPERSTACK_STOCK_URL = "https://infrahub-api.nexgencloud.com/v1/core/stocks"


def normalize_hyperstack_market_state(
    stocks: Iterable[Mapping[str, Any]],
    *,
    observed_at: datetime,
    raw_ref: str | None,
) -> list[ComputeMarketState]:
    rows = []
    for stock in stocks:
        region = str(stock.get("region") or "").strip()
        models = stock.get("models")
        if not isinstance(models, list):
            continue
        for model in models:
            if not isinstance(model, Mapping):
                continue
            gpu_name = str(model.get("model") or "").strip()
            gpu_model = canonical_gpu_model(gpu_name)
            configurations = model.get("configurations")
            if not gpu_model or not isinstance(configurations, Mapping):
                continue
            deployable = []
            for key, value in configurations.items():
                gpu_count = _configuration_gpu_count(key)
                configuration_count = _float_or_none(value)
                if (
                    gpu_count is not None
                    and configuration_count is not None
                    and configuration_count > 0
                ):
                    deployable.append(gpu_count * configuration_count)
            if not deployable:
                continue
            lower_bound = max(deployable)
            rows.append(
                _state(
                    observed_at=observed_at,
                    resource_type=gpu_model,
                    provider="hyperstack",
                    source_connector="hyperstack",
                    source_role="direct",
                    measurement_kind="availability_pressure",
                    measurement_scope=f"region:{region or 'unknown'}",
                    unit="gpu_units_lower_bound",
                    total_units=None,
                    rented_units=None,
                    available_units=float(lower_bound),
                    pending_units=None,
                    rented_share=None,
                    available_share=None,
                    stock_status=str(model.get("available") or "available"),
                    count_precision="max_deployable_configuration_lower_bound",
                    numerator_definition="Largest currently deployable configuration count expressed in GPU units.",
                    denominator_definition="Hyperstack does not expose total fleet GPU units in this response.",
                    source_url=HYPERSTACK_STOCK_URL,
                    raw_ref=raw_ref,
                    notes="Configuration sizes may overlap, so counts are not summed.",
                )
            )
    return rows
