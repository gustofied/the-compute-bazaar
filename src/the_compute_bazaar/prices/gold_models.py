"""Registry and renderer for maintained DataFusion Gold models."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from .sql_models import render_sql, sql_metadata


BENCHMARK_METHODOLOGY_VERSION = "advertised_provider_floor_median_v1"
BENCHMARK_FAMILIES = [
    {"family_id": "H100", "label": "H100", "gpu_model_prefixes": ["H100_"]},
    {"family_id": "H200", "label": "H200", "gpu_model_prefixes": ["H200_"]},
    {"family_id": "B200", "label": "B200", "gpu_model_prefixes": ["B200_"]},
    {"family_id": "B300", "label": "B300", "gpu_model_prefixes": ["B300_"]},
]


@dataclass(frozen=True)
class GoldModel:
    model_id: str
    sql_path: str
    methodology_version: str | None = None


GOLD_MODELS = {
    "fact_gpu_listings": GoldModel(
        "gold_gpu_listings_v1",
        "models/gold/fact_gpu_listings.sql",
    ),
    "dim_gpu_products": GoldModel(
        "gold_gpu_products_v1",
        "models/gold/dim_gpu_products.sql",
    ),
    "dim_providers": GoldModel(
        "gold_providers_v1",
        "models/gold/dim_providers.sql",
    ),
    "dim_regions": GoldModel(
        "gold_regions_v1",
        "models/gold/dim_regions.sql",
    ),
    "fact_price_index_values": GoldModel(
        "gold_gpu_floor_values_v1",
        "models/gold/fact_price_index_values.sql",
    ),
    "fact_index_constituents": GoldModel(
        "gold_gpu_floor_constituents_v1",
        "models/gold/fact_index_constituents.sql",
    ),
    "fact_benchmark_values": GoldModel(
        "benchmark_frontier_gpu_families_v2",
        "models/gold/benchmark_values.sql",
        BENCHMARK_METHODOLOGY_VERSION,
    ),
    "fact_benchmark_constituents": GoldModel(
        "benchmark_frontier_gpu_constituents_v2",
        "models/gold/benchmark_constituents.sql",
        BENCHMARK_METHODOLOGY_VERSION,
    ),
    "fact_compute_market_state": GoldModel(
        "gold_compute_market_state_v1",
        "models/gold/fact_compute_market_state.sql",
    ),
    "fact_prime_frontier_offer_reference_history": GoldModel(
        "gold_prime_offer_reference_v1",
        "models/gold/prime_offer_reference_history.sql",
    ),
    "fact_prime_frontier_offer_ladder": GoldModel(
        "gold_prime_offer_ladder_v1",
        "models/gold/prime_offer_ladder.sql",
    ),
    "sandbox_workload_batch_history": GoldModel(
        "sandbox_workload_batch_history_v2",
        "models/gold/sandbox_workload_batch_history.sql",
    ),
    "sandbox_workload_run_history": GoldModel(
        "sandbox_workload_run_summary_v1",
        "models/gold/sandbox_workload_run_history.sql",
    ),
    "sandbox_workload_latest_replicates": GoldModel(
        "sandbox_workload_latest_replicates_v2",
        "models/gold/sandbox_workload_latest_replicates.sql",
    ),
    "sandbox_workload_latest_phases": GoldModel(
        "sandbox_workload_latest_phases_v1",
        "models/gold/sandbox_workload_latest_phases.sql",
    ),
    "sandbox_workload_phase_summary": GoldModel(
        "sandbox_workload_phase_summary_v1",
        "models/gold/sandbox_workload_phase_summary.sql",
    ),
    "sandbox_workload_service_summary": GoldModel(
        "sandbox_workload_service_summary_v2",
        "models/gold/sandbox_workload_service_summary.sql",
    ),
}


def gold_model_sql(
    table_name: str,
    context: dict[str, Any] | None = None,
    *,
    fragments: dict[str, str] | None = None,
) -> str:
    model = _gold_model(table_name)
    model_context = dict(context or {})
    if model.methodology_version:
        model_context.setdefault("methodology_version", model.methodology_version)
        model_context.setdefault("methodology_query_id", model.model_id)
    return render_sql(model.sql_path, model_context, fragments=fragments)


def gold_sql_models(
    table_names: Iterable[str],
    *,
    methodology_versions: dict[str, str] | None = None,
) -> dict[str, dict[str, str]]:
    metadata: dict[str, dict[str, str]] = {}
    for table_name in table_names:
        model = _gold_model(table_name)
        model_metadata = {
            "model_id": model.model_id,
            **sql_metadata(model.sql_path),
        }
        methodology_version = (methodology_versions or {}).get(
            table_name,
            model.methodology_version,
        )
        if methodology_version:
            model_metadata["methodology_version"] = methodology_version
        metadata[table_name] = model_metadata
    return metadata


def _gold_model(table_name: str) -> GoldModel:
    try:
        return GOLD_MODELS[table_name]
    except KeyError as exc:
        raise KeyError(f"Unknown Gold SQL model: {table_name}") from exc
