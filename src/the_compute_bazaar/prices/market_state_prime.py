"""Normalize Prime Intellect availability observations."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from .normalize import canonical_gpu_model
from .schemas import ComputeMarketState

from .market_state_common import (
    _float_or_none,
    _share,
    _state,
    _stock_available,
    _tightest_stock_status,
    canonical_provider_id,
)


PRIME_AVAILABILITY_URL = "https://api.primeintellect.ai/api/v1/availability/gpus"


def normalize_prime_market_state(
    items: Iterable[Mapping[str, Any]],
    *,
    observed_at: datetime,
    raw_ref: str | None,
) -> list[ComputeMarketState]:
    """Build upstream-preserving availability observations from Prime."""
    groups: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for item in items:
        gpu_name = str(item.get("gpuType") or "").strip()
        gpu_memory = _float_or_none(item.get("gpuMemory"))
        gpu_model = canonical_gpu_model(
            gpu_name,
            gpu_memory * 1024 if gpu_memory is not None else None,
        )
        if not gpu_model:
            continue
        provider = canonical_provider_id(str(item.get("provider") or ""))
        groups[(provider, gpu_model)].append(item)

    rows = []
    for (provider, gpu_model), group in sorted(groups.items()):
        statuses = [str(item.get("stockStatus") or "").strip() for item in group]
        available_count = sum(_stock_available(status) for status in statuses)
        total_count = len(group)
        rows.append(
            _state(
                observed_at=observed_at,
                resource_type=gpu_model,
                provider=provider,
                source_connector="prime_intellect",
                source_role="aggregator",
                measurement_kind="availability_pressure",
                measurement_scope="upstream_listed_configurations",
                unit="configurations",
                total_units=float(total_count),
                rented_units=None,
                available_units=float(available_count),
                pending_units=None,
                rented_share=None,
                available_share=_share(available_count, total_count),
                stock_status=_tightest_stock_status(statuses),
                count_precision="configuration_count",
                numerator_definition="Prime configurations currently carrying an available stock status.",
                denominator_definition=(
                    "All Prime configurations returned for the same upstream "
                    "provider and GPU product."
                ),
                source_url=PRIME_AVAILABILITY_URL,
                raw_ref=raw_ref,
                notes=(
                    "Prime is an aggregator. This is configuration availability, "
                    "not physical GPU-fleet rental occupancy."
                ),
            )
        )
    return rows
