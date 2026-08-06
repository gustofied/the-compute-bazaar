"""Normalize Runpod availability observations."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from .normalize import canonical_gpu_model
from .schemas import ComputeMarketState

from .market_state_common import (
    _float_or_none,
    _state,
)


RUNPOD_GRAPHQL_URL = "https://api.runpod.io/graphql"


def normalize_runpod_market_state(
    gpu_types: Iterable[Mapping[str, Any]],
    *,
    observed_at: datetime,
    raw_ref: str | None,
) -> list[ComputeMarketState]:
    rows = []
    for entry in gpu_types:
        gpu_name = str(entry.get("displayName") or entry.get("id") or "").strip()
        vram_gb = _float_or_none(entry.get("memoryInGb"))
        gpu_model = canonical_gpu_model(
            gpu_name,
            vram_gb * 1024 if vram_gb is not None else None,
        )
        lowest = entry.get("lowestPrice")
        if not gpu_model or not isinstance(lowest, Mapping):
            continue
        status = str(lowest.get("stockStatus") or "").strip()
        bundle_sizes = lowest.get("availableGpuCounts")
        available_sizes = (
            [value for value in bundle_sizes if _float_or_none(value) is not None]
            if isinstance(bundle_sizes, list)
            else []
        )
        rows.append(
            _state(
                observed_at=observed_at,
                resource_type=gpu_model,
                provider="runpod",
                source_connector="runpod",
                source_role="direct",
                measurement_kind="availability_pressure",
                measurement_scope="deployable_bundle_sizes",
                unit="bundle_sizes",
                total_units=None,
                rented_units=None,
                available_units=float(len(available_sizes)),
                pending_units=None,
                rented_share=None,
                available_share=None,
                stock_status=status or "unknown",
                count_precision="categorical_stock_and_bundle_sizes",
                numerator_definition="GPU-count bundle sizes currently returned as deployable.",
                denominator_definition="RunPod does not expose total fleet GPU units in this response.",
                source_url=RUNPOD_GRAPHQL_URL,
                raw_ref=raw_ref,
                notes="Stock status and bundle sizes describe deployability, not rented share.",
            )
        )
    return rows
