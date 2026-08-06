"""Registry and renderer for maintained DataFusion Gold models."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from .sql_models import render_sql, sql_metadata


BENCHMARK_METHODOLOGY_VERSION = "advertised_provider_floor_median_v2"
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
    "dim_sources": GoldModel(
        "gold_sources_v1",
        "models/gold/dim_sources.sql",
    ),
    "fact_gpu_price_index": GoldModel(
        "gpu_price_index_v1",
        "models/gold/gpu_price_index.sql",
        BENCHMARK_METHODOLOGY_VERSION,
    ),
    "fact_gpu_price_index_constituents": GoldModel(
        "gpu_price_index_constituents_v1",
        "models/gold/gpu_price_index_constituents.sql",
        BENCHMARK_METHODOLOGY_VERSION,
    ),
    "fact_compute_market_state": GoldModel(
        "gold_compute_market_state_v1",
        "models/gold/fact_compute_market_state.sql",
    ),
    "fact_gpu_availability": GoldModel(
        "gold_gpu_availability_v1",
        "models/gold/fact_gpu_availability.sql",
    ),
    "fact_gpu_availability_history": GoldModel(
        "gold_gpu_availability_history_v1",
        "models/gold/fact_gpu_availability.sql",
    ),
    "fact_prime_frontier_offer_reference_history": GoldModel(
        "gold_prime_offer_reference_v1",
        "models/gold/prime_offer_reference_history.sql",
    ),
    "fact_prime_frontier_offer_ladder": GoldModel(
        "gold_prime_offer_ladder_v1",
        "models/gold/prime_offer_ladder.sql",
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
