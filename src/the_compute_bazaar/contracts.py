"""Canonical names for Compute Bazaar data boundaries."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


GPU_OFFERS_RUN_CONTRACT = "compute_bazaar_gpu_offers_run"
GOLD_MARKET_CONTRACT = "compute_bazaar_gold_market"
MARKET_RUN_CONTRACT = "compute_bazaar_market_run"
MARKET_EVENT_CONTRACT = "compute_bazaar_market_event"
PORTABLE_LAKE_CONTRACT = "compute_bazaar_portable_lake"
CARD_CONTRACT = "compute_bazaar_card"
PUBLICATION_CONTRACT = "compute_bazaar_publication"
PUBLICATION_ROUTE_CONTRACT = "compute_bazaar_publication_route"
SANDBOX_SOURCE_CONTRACT = "sandbox_source_manifest"
SANDBOX_OBSERVATION_CONTRACT = "sandbox_benchmark_observation"
SANDBOX_WORKLOAD_INPUT_CONTRACT = "sandbox_workload_cost_input"
SANDBOX_WORKLOAD_DATASET_CONTRACT = "sandbox_workload_dataset"
SANDBOX_WORKLOAD_POLL_CONTRACT = "sandbox_workload_poll"
SANDBOX_WORKLOAD_GOLD_CONTRACT = "sandbox_workload_cost_gold"

_RETIRED_CONTRACT_KEYS = {
    "schema_version",
    "manifest_version",
    "route_schema_version",
}


def transform_contract(
    payload: Mapping[str, Any],
    *,
    contract: str,
) -> dict[str, Any]:
    """Project retained metadata into the one current contract."""
    transformed = {
        key: value
        for key, value in payload.items()
        if key not in _RETIRED_CONTRACT_KEYS
    }
    transformed["contract"] = contract
    return transformed


def require_contract(payload: Mapping[str, Any], *, contract: str) -> None:
    if payload.get("contract") != contract:
        raise RuntimeError(f"Expected {contract}")
