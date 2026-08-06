"""Normalize Akash capacity observations."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from .normalize import canonical_gpu_model
from .schemas import ComputeMarketState

from .market_state_common import (
    _availability_label,
    _float_or_none,
    _float_or_zero,
    _gib_value,
    _share,
    _state,
)


AKASH_PROVIDERS_URL = "https://console-api.akash.network/v1/providers"
AKASH_GPU_PRICES_URL = "https://console-api.akash.network/v1/gpu-prices"


def normalize_akash_market_state(
    *,
    models: Iterable[Mapping[str, Any]],
    providers: Iterable[Mapping[str, Any]],
    observed_at: datetime,
    raw_ref: str | None,
) -> list[ComputeMarketState]:
    """Build network active-capacity shares and model availability from Akash."""
    rows: list[ComputeMarketState] = []
    online_providers = [
        provider for provider in providers if provider.get("isOnline") is True
    ]
    resource_specs = (
        (
            "gpu",
            "ALL_GPU",
            "gpu",
            "gpu_units",
            ("gpu",),
            "GPU units",
        ),
        (
            "cpu",
            "ALL_CPU",
            "cpu",
            "millicpu",
            ("cpu",),
            "CPU capacity",
        ),
        (
            "memory",
            "ALL_MEMORY",
            "memory",
            "bytes",
            ("memory",),
            "memory",
        ),
        (
            "storage",
            "ALL_STORAGE",
            "storage",
            "bytes",
            ("storage", "total"),
            "storage",
        ),
        (
            "storage",
            "ALL_EPHEMERAL_STORAGE",
            "storage_ephemeral",
            "bytes",
            ("storage", "ephemeral"),
            "ephemeral storage",
        ),
        (
            "storage",
            "ALL_PERSISTENT_STORAGE",
            "storage_persistent",
            "bytes",
            ("storage", "persistent"),
            "persistent storage",
        ),
    )
    for (
        resource_market,
        resource_type,
        scope_name,
        unit,
        stats_path,
        label,
    ) in resource_specs:
        aggregate = _aggregate_akash_resource(online_providers, stats_path)
        if aggregate["total"] <= 0:
            continue
        rows.append(
            _state(
                observed_at=observed_at,
                resource_market=resource_market,
                resource_type=resource_type,
                provider="akash",
                source_connector="akash",
                source_role="direct",
                measurement_kind="rental_occupancy",
                measurement_scope=f"online_provider_{scope_name}_capacity",
                unit=unit,
                total_units=aggregate["total"],
                rented_units=aggregate["active"],
                available_units=aggregate["available"],
                pending_units=aggregate["pending"],
                rented_share=_share(aggregate["active"], aggregate["total"]),
                available_share=_share(aggregate["available"], aggregate["total"]),
                stock_status=None,
                count_precision="reported_counts",
                numerator_definition=(
                    f"{label.capitalize()} reported active and consumed by "
                    "deployments on online Akash providers."
                ),
                denominator_definition=(
                    f"Total {label} reported by the same online Akash providers."
                ),
                source_url=AKASH_PROVIDERS_URL,
                raw_ref=raw_ref,
                notes=(
                    f"Aggregated across {int(aggregate['provider_count'])} "
                    "online providers reporting this resource."
                ),
            )
        )

    for model in models:
        gpu_name = str(model.get("model") or "").strip()
        vram_gb = _gib_value(model.get("ram"))
        gpu_model = canonical_gpu_model(
            gpu_name,
            vram_gb * 1024 if vram_gb is not None else None,
        )
        availability_row = model.get("availability")
        if not gpu_model or not isinstance(availability_row, Mapping):
            continue
        model_total = _float_or_none(availability_row.get("total"))
        model_available = _float_or_none(availability_row.get("available"))
        if model_total is None or model_total <= 0 or model_available is None:
            continue
        rows.append(
            _state(
                observed_at=observed_at,
                resource_type=gpu_model,
                provider="akash",
                source_connector="akash",
                source_role="direct",
                measurement_kind="availability_pressure",
                measurement_scope="gpu_model_units",
                unit="gpu_units",
                total_units=model_total,
                rented_units=None,
                available_units=model_available,
                pending_units=None,
                rented_share=None,
                available_share=_share(model_available, model_total),
                stock_status=_availability_label(model_available, model_total),
                count_precision="reported_counts",
                numerator_definition="GPU units currently reported available for this Akash model.",
                denominator_definition="Total GPU units reported for this Akash model.",
                source_url=AKASH_GPU_PRICES_URL,
                raw_ref=raw_ref,
                notes="Model availability does not identify how unavailable units split between active and pending.",
            )
        )
    return rows


def _aggregate_akash_resource(
    providers: Iterable[Mapping[str, Any]],
    stats_path: tuple[str, ...],
) -> dict[str, float]:
    aggregate = {
        "active": 0.0,
        "available": 0.0,
        "pending": 0.0,
        "total": 0.0,
        "provider_count": 0.0,
    }
    for provider in providers:
        value: Any = provider.get("stats")
        for key in stats_path:
            value = value.get(key) if isinstance(value, Mapping) else None
        if not isinstance(value, Mapping):
            continue
        total = _float_or_none(value.get("total"))
        if total is None or total < 0:
            continue
        aggregate["provider_count"] += 1
        aggregate["total"] += total
        aggregate["active"] += _float_or_zero(value.get("active"))
        aggregate["available"] += _float_or_zero(value.get("available"))
        aggregate["pending"] += _float_or_zero(value.get("pending"))
    return aggregate
