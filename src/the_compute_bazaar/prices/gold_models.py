"""Registry and renderer for maintained DataFusion Gold models."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from .sql_models import render_sql, sql_metadata


BENCHMARK_METHODOLOGY = "provider_floor_median"
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
    methodology: str | None = None


GOLD_MODELS = {
    "fact_gpu_listings": GoldModel(
        "fact_gpu_listings",
        "models/gold/fact_gpu_listings.sql",
    ),
    "dim_gpu_products": GoldModel(
        "dim_gpu_products",
        "models/gold/dim_gpu_products.sql",
    ),
    "dim_providers": GoldModel(
        "dim_providers",
        "models/gold/dim_providers.sql",
    ),
    "dim_sources": GoldModel(
        "dim_sources",
        "models/gold/dim_sources.sql",
    ),
    "fact_gpu_price_index": GoldModel(
        "fact_gpu_price_index",
        "models/gold/gpu_price_index.sql",
        BENCHMARK_METHODOLOGY,
    ),
    "fact_gpu_price_index_constituents": GoldModel(
        "fact_gpu_price_index_constituents",
        "models/gold/gpu_price_index_constituents.sql",
        BENCHMARK_METHODOLOGY,
    ),
    "fact_compute_market_state": GoldModel(
        "fact_compute_market_state",
        "models/gold/fact_compute_market_state.sql",
    ),
    "fact_gpu_availability": GoldModel(
        "fact_gpu_availability",
        "models/gold/fact_gpu_availability.sql",
    ),
    "fact_gpu_availability_history": GoldModel(
        "fact_gpu_availability_history",
        "models/gold/fact_gpu_availability.sql",
    ),
    "fact_prime_frontier_offer_reference_history": GoldModel(
        "fact_prime_frontier_offer_reference_history",
        "models/gold/prime_offer_reference_history.sql",
    ),
    "fact_prime_frontier_offer_ladder": GoldModel(
        "fact_prime_frontier_offer_ladder",
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
    if model.methodology:
        model_context.setdefault("methodology_version", model.methodology)
        model_context.setdefault("methodology_query_id", model.model_id)
    return render_sql(model.sql_path, model_context, fragments=fragments)


def gold_sql_models(
    table_names: Iterable[str],
    *,
    methodologies: dict[str, str] | None = None,
) -> dict[str, dict[str, str]]:
    metadata: dict[str, dict[str, str]] = {}
    for table_name in table_names:
        model = _gold_model(table_name)
        model_metadata = {
            "model_id": model.model_id,
            **sql_metadata(model.sql_path),
        }
        methodology = (methodologies or {}).get(
            table_name,
            model.methodology,
        )
        if methodology:
            model_metadata["methodology"] = methodology
        metadata[table_name] = model_metadata
    return metadata


def _gold_model(table_name: str) -> GoldModel:
    try:
        return GOLD_MODELS[table_name]
    except KeyError as exc:
        raise KeyError(f"Unknown Gold SQL model: {table_name}") from exc
