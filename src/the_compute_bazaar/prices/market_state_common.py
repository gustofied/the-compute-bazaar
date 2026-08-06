"""Shared constructors for source-honest compute market state."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from .schemas import ComputeMarketState


PROVIDER_ALIASES = {
    "lambda_labs": "lambda",
    "lambdalabs": "lambda",
    "massed_compute": "massed_compute",
    "massedcompute": "massed_compute",
}


def canonical_provider_id(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    return PROVIDER_ALIASES.get(normalized, normalized) or "prime_intellect"


def _state(
    *,
    observed_at: datetime,
    resource_market: str = "gpu",
    resource_type: str,
    provider: str,
    source_connector: str,
    source_role: str,
    measurement_kind: str,
    measurement_scope: str,
    unit: str,
    total_units: float | None,
    rented_units: float | None,
    available_units: float | None,
    pending_units: float | None,
    rented_share: float | None,
    available_share: float | None,
    stock_status: str | None,
    count_precision: str,
    numerator_definition: str,
    denominator_definition: str,
    source_url: str,
    raw_ref: str | None,
    notes: str | None,
) -> ComputeMarketState:
    identity = "|".join(
        [
            observed_at.isoformat(),
            provider,
            source_connector,
            resource_type,
            measurement_kind,
            measurement_scope,
            unit,
        ]
    )
    observation_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    return ComputeMarketState(
        observation_id=observation_id,
        observed_at=observed_at,
        resource_market=resource_market,
        resource_type=resource_type,
        provider=provider,
        source_connector=source_connector,
        source_role=source_role,
        measurement_kind=measurement_kind,
        measurement_scope=measurement_scope,
        unit=unit,
        total_units=total_units,
        rented_units=rented_units,
        available_units=available_units,
        pending_units=pending_units,
        rented_share=rented_share,
        available_share=available_share,
        stock_status=stock_status,
        count_precision=count_precision,
        numerator_definition=numerator_definition,
        denominator_definition=denominator_definition,
        aggregation_eligible=True,
        aggregation_exclusion_reason=None,
        source_url=source_url,
        raw_ref=raw_ref,
        notes=notes,
    )


def _gib_value(value: Any) -> float | None:
    import re

    match = re.search(r"\d+(?:\.\d+)?", str(value or ""))
    return float(match.group()) if match else None


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _float_or_zero(value: Any) -> float:
    return _float_or_none(value) or 0.0


def _share(numerator: float, denominator: float) -> float | None:
    if denominator <= 0:
        return None
    return max(0.0, min(1.0, numerator / denominator))


def _availability_label(available: float, total: float) -> str:
    share = _share(available, total) or 0.0
    if available <= 0:
        return "none"
    if share < 0.1:
        return "low"
    if share < 0.35:
        return "medium"
    return "high"


def _stock_available(status: str) -> int:
    return int(status.strip().lower() not in {"", "none", "unavailable"})


def _tightest_stock_status(statuses: Iterable[str]) -> str:
    order = {"none": 0, "unavailable": 0, "low": 1, "medium": 2, "high": 3}
    normalized = [status.strip().lower() for status in statuses if status.strip()]
    if not normalized:
        return "unknown"
    return min(normalized, key=lambda status: order.get(status, 2))


def _configuration_gpu_count(value: Any) -> float | None:
    text = str(value or "").strip().lower()
    if not text.endswith("x"):
        return None
    return _float_or_none(text[:-1])
