"""Build gold market tables from normalized GPU offers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ..contracts import GOLD_MARKET_CONTRACT
from .gold_models import BENCHMARK_METHODOLOGY, gold_model_sql, gold_sql_models
from .gold_manifest import (
    GOLD_MANIFEST_TABLE,
    gold_manifest_ref,
    latest_gold_manifest_ref,
    read_latest_gold_manifest,
)
from .datafusion import DataFusionEngine, TableRef
from .gold_sources import (
    gpu_price_index_history_row,
    history_seed_ref,
    merge_compute_market_state_history,
    merge_gpu_price_index_history,
    normalize_compute_market_state_history,
    normalize_gpu_price_index_history,
    retained_history_count,
    retained_history_refs,
    silver_source_cte,
    silver_state_cte_fragment,
    silver_state_union_fragment,
    source_catalog_values,
)
from .manifest import read_latest_manifest
from .offer_reference import PRIME_FRONTIER_METHODOLOGY
from .prime_gold import (
    PRIME_FRONTIER_GOLD_TABLES,
    build_prime_frontier_gold_products,
)
from .provider_registry import registered_provider_names
from .schemas import to_jsonable, utc_now
from .storage import table_partition, write_json, write_parquet_rows


GOLD_METHODOLOGY = "gpu_market_gold"
MARKET_STATE_METHODOLOGY = "compute_market_state"
GOLD_TABLES = {
    "fact_gpu_listings": "listings.parquet",
    "dim_gpu_products": "gpu_products.parquet",
    "dim_providers": "providers.parquet",
    "dim_sources": "sources.parquet",
    "fact_gpu_price_index": "gpu_price_index.parquet",
    "fact_gpu_price_index_history": "gpu_price_index_history.parquet",
    "fact_gpu_price_index_constituents": "gpu_price_index_constituents.parquet",
    "fact_compute_market_state": "compute_market_state.parquet",
    "fact_compute_market_state_history": "compute_market_state_history.parquet",
    "fact_gpu_availability": "gpu_availability.parquet",
    "fact_gpu_availability_history": "gpu_availability_history.parquet",
}
CORE_GOLD_SQL_TABLES = (
    "fact_gpu_listings",
    "dim_gpu_products",
    "dim_providers",
    "dim_sources",
    "fact_compute_market_state",
    "fact_gpu_availability",
    "fact_gpu_availability_history",
)


@dataclass(frozen=True)
class GoldBuildResult:
    run_id: str
    provider_scope: list[str]
    source_run_ids: dict[str, str]
    source_normalized_refs: dict[str, str]
    source_market_state_refs: dict[str, str]
    observed_date: str
    table_refs: dict[str, TableRef]
    row_counts: dict[str, int]
    manifest_ref: str

    def to_dict(self) -> dict[str, Any]:
        return to_jsonable(self)


def build_gold_market_tables(
    *,
    lake_root: str,
    provider: str = "vast",
    providers: list[str] | None = None,
    run_id: str | None = None,
    calculated_at: str | None = None,
    manifest_observed_at: str | None = None,
) -> GoldBuildResult:
    """Build gold market tables from latest silver provider manifests."""
    try:
        previous_gold_manifest = read_latest_gold_manifest(lake_root)
    except (FileNotFoundError, OSError):
        previous_gold_manifest = {}
    except Exception as exc:  # noqa: BLE001 - S3 returns provider-specific not-found errors.
        error_code = getattr(exc, "response", {}).get("Error", {}).get("Code")
        if str(error_code or "") not in {"404", "NoSuchKey", "NotFound"}:
            raise
        previous_gold_manifest = {}

    provider_scope = providers or [provider]
    source_manifests = {
        source_provider: read_latest_manifest(lake_root, provider=source_provider)
        for source_provider in provider_scope
    }
    source_normalized_refs: dict[str, str] = {}
    source_market_state_refs: dict[str, str] = {}
    source_run_ids: dict[str, str] = {}
    for source_provider, manifest in source_manifests.items():
        normalized_ref = manifest.get("normalized_ref")
        if not normalized_ref:
            raise RuntimeError(
                f"Latest {source_provider} manifest has no normalized_ref"
            )
        source_normalized_refs[source_provider] = str(normalized_ref)
        market_state_ref = manifest.get("market_state_ref")
        if market_state_ref:
            source_market_state_refs[source_provider] = str(market_state_ref)
        source_run_ids[source_provider] = str(manifest["run_id"])

    observed_date = max(
        _observed_date(manifest) for manifest in source_manifests.values()
    )
    source_slug = "-".join(f"{name}-{source_run_ids[name]}" for name in provider_scope)
    gold_run_id = run_id or f"gold-{source_slug}"

    table_refs: dict[str, TableRef] = {
        table_name: table_partition(
            lake_root,
            table=f"gold/{table_name}",
            observed_date=observed_date,
            provider=None,
            run_id=gold_run_id,
            filename=filename,
        )
        for table_name, filename in GOLD_TABLES.items()
    }

    calculated_at_value = calculated_at or utc_now().isoformat()
    gold_observed_at = manifest_observed_at or calculated_at_value
    query_context = {
        "gold_run_id": gold_run_id,
        "gold_observed_date": observed_date,
        "calculated_at": calculated_at_value,
        "market_state_methodology_version": MARKET_STATE_METHODOLOGY,
    }

    tables = {
        f"silver_offer_observations_{index}": source_normalized_refs[source_provider]
        for index, source_provider in enumerate(provider_scope)
    }
    engine = DataFusionEngine(tables)
    silver_source_cte_sql = silver_source_cte(list(tables))
    source_catalog_values_sql = source_catalog_values(provider_scope)
    rows_by_table = {
        "fact_gpu_listings": engine.query(
            gold_model_sql(
                "fact_gpu_listings",
                query_context,
                fragments={
                    "silver_source_cte": silver_source_cte_sql,
                    "source_catalog_values": source_catalog_values_sql,
                },
            ),
        ),
        "dim_gpu_products": engine.query(
            gold_model_sql(
                "dim_gpu_products",
                query_context,
                fragments={"silver_source_cte": silver_source_cte_sql},
            ),
        ),
        "dim_providers": engine.query(
            gold_model_sql(
                "dim_providers",
                query_context,
                fragments={"silver_source_cte": silver_source_cte_sql},
            ),
        ),
        "dim_sources": engine.query(
            gold_model_sql(
                "dim_sources",
                query_context,
                fragments={
                    "silver_source_cte": silver_source_cte_sql,
                    "source_catalog_values": source_catalog_values_sql,
                },
            ),
        ),
    }
    market_state_tables = {
        f"silver_compute_market_state_{index}": source_market_state_refs[
            source_provider
        ]
        for index, source_provider in enumerate(provider_scope)
        if source_provider in source_market_state_refs
    }
    if market_state_tables:
        engine.register_tables(market_state_tables)
    rows_by_table["fact_compute_market_state"] = engine.query(
        gold_model_sql(
            "fact_compute_market_state",
            query_context,
            fragments={
                "silver_source_cte": silver_source_cte_sql,
                "state_cte": silver_state_cte_fragment(list(market_state_tables)),
                "state_union": silver_state_union_fragment(bool(market_state_tables)),
            },
        ),
    )
    previous_table_refs = dict(previous_gold_manifest.get("table_refs") or {})
    history_counts: dict[str, int] = {}
    market_history_name = "fact_compute_market_state_history"
    previous_market_history_ref = previous_table_refs.get(market_history_name)
    market_history_part_ref = str(table_refs[market_history_name])
    market_history_seed = history_seed_ref(previous_market_history_ref)
    if market_history_seed:
        market_history_rows = merge_compute_market_state_history(
            previous_ref=market_history_seed,
            current_rows=rows_by_table["fact_compute_market_state"],
            methodology=MARKET_STATE_METHODOLOGY,
            retained_source_connectors=set(registered_provider_names()),
        )
    else:
        market_history_rows = normalize_compute_market_state_history(
            rows_by_table["fact_compute_market_state"],
            methodology=MARKET_STATE_METHODOLOGY,
            retained_source_connectors=set(registered_provider_names()),
        )
    rows_by_table[market_history_name] = market_history_rows
    if market_history_rows:
        write_parquet_rows(market_history_part_ref, market_history_rows)
    table_refs[market_history_name] = retained_history_refs(
        previous_market_history_ref,
        market_history_part_ref,
        part_written=bool(market_history_rows),
    )
    history_counts[market_history_name] = retained_history_count(
        previous_gold_manifest,
        market_history_name,
        previous_market_history_ref,
        market_history_part_ref,
        market_history_rows,
    )

    write_parquet_rows(
        str(table_refs["fact_compute_market_state"]),
        rows_by_table["fact_compute_market_state"],
    )
    engine.register_tables(
        {
            "fact_compute_market_state": table_refs["fact_compute_market_state"],
            market_history_name: table_refs[market_history_name],
        }
    )
    rows_by_table["fact_gpu_availability"] = engine.query(
        gold_model_sql(
            "fact_gpu_availability",
            fragments={"source_table": "fact_compute_market_state"},
        )
    )
    availability_history_name = "fact_gpu_availability_history"
    previous_availability_ref = previous_table_refs.get(availability_history_name)
    availability_history_part_ref = str(table_refs[availability_history_name])
    if history_seed_ref(previous_availability_ref):
        availability_history_rows = engine.query(
            gold_model_sql(
                availability_history_name,
                fragments={"source_table": market_history_name},
            )
        )
    else:
        availability_history_rows = list(rows_by_table["fact_gpu_availability"])
    rows_by_table[availability_history_name] = availability_history_rows
    if availability_history_rows:
        write_parquet_rows(availability_history_part_ref, availability_history_rows)
    table_refs[availability_history_name] = retained_history_refs(
        previous_availability_ref,
        availability_history_part_ref,
        part_written=bool(availability_history_rows),
    )
    history_counts[availability_history_name] = retained_history_count(
        previous_gold_manifest,
        availability_history_name,
        previous_availability_ref,
        availability_history_part_ref,
        availability_history_rows,
    )

    for table_name, rows in rows_by_table.items():
        if table_name not in {
            "fact_compute_market_state",
            market_history_name,
            availability_history_name,
        }:
            write_parquet_rows(str(table_refs[table_name]), rows)

    engine.register_tables({"fact_gpu_listings": table_refs["fact_gpu_listings"]})
    benchmark_constituents = engine.query(
        gold_model_sql("fact_gpu_price_index_constituents", query_context)
    )
    rows_by_table["fact_gpu_price_index_constituents"] = benchmark_constituents
    write_parquet_rows(
        table_refs["fact_gpu_price_index_constituents"],
        benchmark_constituents,
    )
    engine.register_tables(
        {
            "fact_gpu_price_index_constituents": table_refs[
                "fact_gpu_price_index_constituents"
            ]
        }
    )
    benchmark_values = engine.query(
        gold_model_sql("fact_gpu_price_index", query_context)
    )
    rows_by_table["fact_gpu_price_index"] = benchmark_values
    write_parquet_rows(table_refs["fact_gpu_price_index"], benchmark_values)
    price_history_name = "fact_gpu_price_index_history"
    previous_price_history_ref = previous_table_refs.get(price_history_name)
    price_history_part_ref = str(table_refs[price_history_name])
    if history_seed_ref(previous_price_history_ref):
        price_history_rows = merge_gpu_price_index_history(
            previous_ref=history_seed_ref(previous_price_history_ref),
            current_rows=benchmark_values,
            gold_run_id=gold_run_id,
            gold_observed_at=gold_observed_at,
            gold_observed_date=observed_date,
            methodology=BENCHMARK_METHODOLOGY,
        )
    else:
        price_history_rows = normalize_gpu_price_index_history(
            [
                gpu_price_index_history_row(
                    row,
                    gold_run_id=gold_run_id,
                    gold_observed_at=gold_observed_at,
                    gold_observed_date=observed_date,
                )
                for row in benchmark_values
            ],
            methodology=BENCHMARK_METHODOLOGY,
        )
    rows_by_table[price_history_name] = price_history_rows
    if price_history_rows:
        write_parquet_rows(price_history_part_ref, price_history_rows)
    table_refs[price_history_name] = retained_history_refs(
        previous_price_history_ref,
        price_history_part_ref,
        part_written=bool(price_history_rows),
    )
    history_counts[price_history_name] = retained_history_count(
        previous_gold_manifest,
        price_history_name,
        previous_price_history_ref,
        price_history_part_ref,
        price_history_rows,
    )

    prime_frontier_rows, prime_frontier_refs, prime_frontier_counts = (
        build_prime_frontier_gold_products(
            lake_root=lake_root,
            previous_gold_manifest=previous_gold_manifest,
            current_listing_rows=rows_by_table["fact_gpu_listings"],
            observed_date=observed_date,
            gold_run_id=gold_run_id,
            gold_observed_at=gold_observed_at,
            gpu_price_index_ref=table_refs["fact_gpu_price_index"],
        )
    )
    rows_by_table.update(prime_frontier_rows)
    table_refs.update(prime_frontier_refs)
    for table_name in PRIME_FRONTIER_GOLD_TABLES:
        rows_by_table.setdefault(table_name, [])

    row_counts = {table_name: len(rows) for table_name, rows in rows_by_table.items()}
    row_counts.update(history_counts)
    row_counts.update(prime_frontier_counts)
    executed_gold_models = [*CORE_GOLD_SQL_TABLES]
    if "fact_prime_frontier_offer_reference_history" in table_refs:
        executed_gold_models.append("fact_prime_frontier_offer_reference_history")
    if "fact_prime_frontier_offer_ladder" in table_refs:
        executed_gold_models.append("fact_prime_frontier_offer_ladder")
    executed_gold_models.extend(
        ["fact_gpu_price_index", "fact_gpu_price_index_constituents"]
    )
    sql_models = gold_sql_models(
        executed_gold_models,
        methodologies={
            "fact_compute_market_state": MARKET_STATE_METHODOLOGY,
            "fact_prime_frontier_offer_reference_history": PRIME_FRONTIER_METHODOLOGY,
            "fact_prime_frontier_offer_ladder": PRIME_FRONTIER_METHODOLOGY,
        },
    )
    manifest_ref = write_gold_manifest(
        lake_root=lake_root,
        provider_scope=provider_scope,
        run_id=gold_run_id,
        observed_date=observed_date,
        source_manifests=source_manifests,
        table_refs=table_refs,
        row_counts=row_counts,
        sql_models=sql_models,
        observed_at=gold_observed_at,
    )

    return GoldBuildResult(
        run_id=gold_run_id,
        provider_scope=provider_scope,
        source_run_ids=source_run_ids,
        source_normalized_refs=source_normalized_refs,
        source_market_state_refs=source_market_state_refs,
        observed_date=observed_date,
        table_refs=table_refs,
        row_counts=row_counts,
        manifest_ref=manifest_ref,
    )


def write_gold_manifest(
    *,
    lake_root: str,
    provider_scope: list[str],
    run_id: str,
    observed_date: str,
    source_manifests: dict[str, dict[str, Any]],
    table_refs: dict[str, TableRef],
    row_counts: dict[str, int],
    sql_models: dict[str, dict[str, str]] | None = None,
    observed_at: str | None = None,
) -> str:
    manifest_ref = gold_manifest_ref(
        lake_root, observed_date=observed_date, run_id=run_id
    )
    payload = {
        "contract": GOLD_MARKET_CONTRACT,
        "table": GOLD_MANIFEST_TABLE,
        "methodology": GOLD_METHODOLOGY,
        "provider_scope": provider_scope,
        "run_id": run_id,
        "observed_at": observed_at or utc_now().isoformat(),
        "observed_date": observed_date,
        "source_manifest_refs": {
            source_provider: manifest.get("manifest_ref")
            for source_provider, manifest in source_manifests.items()
        },
        "source_run_ids": {
            source_provider: manifest.get("run_id")
            for source_provider, manifest in source_manifests.items()
        },
        "source_normalized_refs": {
            source_provider: manifest.get("normalized_ref")
            for source_provider, manifest in source_manifests.items()
        },
        "source_market_state_refs": {
            source_provider: manifest.get("market_state_ref")
            for source_provider, manifest in source_manifests.items()
            if manifest.get("market_state_ref")
        },
        "table_refs": table_refs,
        "row_counts": row_counts,
        "sql_models": sql_models or {},
        "manifest_ref": manifest_ref,
    }
    write_json(manifest_ref, payload)
    write_json(latest_gold_manifest_ref(lake_root), payload)
    return manifest_ref


def _observed_date(manifest: dict[str, Any]) -> str:
    observed_at = str(manifest.get("observed_at") or "")
    if observed_at:
        normalized = observed_at.replace("Z", "+00:00")
        try:
            return (
                datetime.fromisoformat(normalized)
                .astimezone(timezone.utc)
                .date()
                .isoformat()
            )
        except ValueError:
            pass
    return utc_now().date().isoformat()
