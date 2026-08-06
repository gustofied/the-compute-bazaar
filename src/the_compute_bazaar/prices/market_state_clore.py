"""Normalize Clore marketplace capacity observations."""

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
)


CLORE_MARKETPLACE_URL = "https://api.clore.ai/v1/marketplace"


def normalize_clore_market_state(
    servers: Iterable[Mapping[str, Any]],
    *,
    observed_at: datetime,
    raw_ref: str | None,
) -> list[ComputeMarketState]:
    """Build server-weighted on-demand rental occupancy from Clore."""
    groups: dict[str, list[bool]] = defaultdict(list)
    for server in servers:
        rented = server.get("rented")
        if not isinstance(rented, bool):
            continue
        groups["ALL_GPU"].append(rented)
        gpu_model = _clore_gpu_model(server)
        if gpu_model:
            groups[gpu_model].append(rented)

    rows = []
    for resource_type, states in sorted(groups.items()):
        total = float(len(states))
        rented = float(sum(states))
        available = total - rented
        rows.append(
            _state(
                observed_at=observed_at,
                resource_type=resource_type,
                provider="clore",
                source_connector="clore",
                source_role="direct",
                measurement_kind="rental_occupancy",
                measurement_scope="public_marketplace_on_demand_servers",
                unit="servers",
                total_units=total,
                rented_units=rented,
                available_units=available,
                pending_units=None,
                rented_share=_share(rented, total),
                available_share=_share(available, total),
                stock_status=None,
                count_precision="derived_from_reported_boolean",
                numerator_definition="Public marketplace servers whose on-demand rented flag is true.",
                denominator_definition="Public marketplace servers with a reported on-demand rented flag.",
                source_url=CLORE_MARKETPLACE_URL,
                raw_ref=raw_ref,
                notes="Server-weighted and on-demand only; active spot offers are not included in the numerator.",
            )
        )
    return rows


def _clore_gpu_model(server: Mapping[str, Any]) -> str | None:
    specs = server.get("specs") if isinstance(server.get("specs"), Mapping) else {}
    gpu_array = server.get("gpu_array")
    gpu_names = (
        [str(value).strip() for value in gpu_array if str(value).strip()]
        if isinstance(gpu_array, list)
        else []
    )
    raw_name = gpu_names[0] if gpu_names else str(specs.get("gpu") or "").strip()
    vram_gb = _float_or_none(specs.get("gpuram"))
    return canonical_gpu_model(
        raw_name,
        vram_gb * 1024 if vram_gb is not None else None,
    )
