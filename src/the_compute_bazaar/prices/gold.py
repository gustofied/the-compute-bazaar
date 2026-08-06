"""Build gold market tables from normalized GPU offers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .gold_models import gold_model_sql, gold_sql_models
from .gold_manifest import (
    GOLD_MANIFEST_TABLE,
    GOLD_MANIFEST_VERSION,
    gold_manifest_ref,
    latest_gold_manifest_ref,
    read_latest_gold_manifest,
)
from .datafusion import query_parquet, query_tables
from .gold_sources import (
    merge_compute_market_state_history,
    silver_source_cte,
    silver_state_cte_fragment,
    silver_state_union_fragment,
    source_catalog_values,
)
from .manifest import read_latest_manifest
from .offer_reference import PRIME_FRONTIER_METHOD_VERSION
from .prime_gold import (
    PRIME_FRONTIER_GOLD_TABLES,
    build_prime_frontier_gold_products,
)
from .schemas import to_jsonable, utc_now
from .storage import table_partition, write_json, write_parquet_rows


GOLD_METHODOLOGY_VERSION = "gold_gpu_market_v4"
MARKET_STATE_METHODOLOGY_VERSION = "compute_market_state_gold_v1"
GOLD_TABLES = {
    "fact_gpu_listings": "listings.parquet",
    "dim_gpu_products": "gpu_products.parquet",
    "dim_providers": "providers.parquet",
    "dim_sources": "sources.parquet",
    "fact_benchmark_values": "benchmark_values.parquet",
    "fact_benchmark_constituents": "benchmark_constituents.parquet",
    "fact_compute_market_state": "compute_market_state.parquet",
    "fact_compute_market_state_history": "compute_market_state_history.parquet",
}
CORE_GOLD_SQL_TABLES = (
    "fact_gpu_listings",
    "dim_gpu_products",
    "dim_providers",
    "dim_sources",
    "fact_compute_market_state",
)
@dataclass(frozen=True)
class GoldBuildResult:
    run_id: str
    provider_scope: list[str]
    source_run_ids: dict[str, str]
    source_normalized_refs: dict[str, str]
    source_market_state_refs: dict[str, str]
    observed_date: str
    table_refs: dict[str, str]
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

    table_refs = {
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

    query_context = {
        "source_run_id": ",".join(
            f"{name}:{source_run_ids[name]}" for name in provider_scope
        ),
        "source_manifest_ref": ",".join(
            str(source_manifests[name].get("manifest_ref") or "")
            for name in provider_scope
        ),
        "source_raw_ref": ",".join(
            str(source_manifests[name].get("raw_ref") or "") for name in provider_scope
        ),
        "source_normalized_ref": ",".join(
            source_normalized_refs[name] for name in provider_scope
        ),
        "source_market_state_ref": ",".join(
            source_market_state_refs[name]
            for name in provider_scope
            if name in source_market_state_refs
        ),
        "gold_run_id": gold_run_id,
        "gold_observed_date": observed_date,
        "calculated_at": utc_now().isoformat(),
        "market_state_methodology_version": MARKET_STATE_METHODOLOGY_VERSION,
    }

    tables = {
        f"silver_gpu_offers_{index}": source_normalized_refs[source_provider]
        for index, source_provider in enumerate(provider_scope)
    }
    silver_source_cte_sql = silver_source_cte(list(tables))
    source_catalog_values_sql = source_catalog_values(provider_scope)
    rows_by_table = {
        "fact_gpu_listings": query_tables(
            tables=tables,
            sql=gold_model_sql(
                "fact_gpu_listings",
                query_context,
                fragments={
                    "silver_source_cte": silver_source_cte_sql,
                    "source_catalog_values": source_catalog_values_sql,
                },
            ),
        ),
        "dim_gpu_products": query_tables(
            tables=tables,
            sql=gold_model_sql(
                "dim_gpu_products",
                query_context,
                fragments={"silver_source_cte": silver_source_cte_sql},
            ),
        ),
        "dim_providers": query_tables(
            tables=tables,
            sql=gold_model_sql(
                "dim_providers",
                query_context,
                fragments={"silver_source_cte": silver_source_cte_sql},
            ),
        ),
        "dim_sources": query_tables(
            tables=tables,
            sql=gold_model_sql(
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
    rows_by_table["fact_compute_market_state"] = query_tables(
        tables={**tables, **market_state_tables},
        sql=gold_model_sql(
            "fact_compute_market_state",
            query_context,
            fragments={
                "silver_source_cte": silver_source_cte_sql,
                "state_cte": silver_state_cte_fragment(list(market_state_tables)),
                "state_union": silver_state_union_fragment(bool(market_state_tables)),
            },
        ),
    )
    rows_by_table["fact_compute_market_state_history"] = (
        merge_compute_market_state_history(
            previous_ref=previous_gold_manifest.get("table_refs", {}).get(
                "fact_compute_market_state_history"
            ),
            current_rows=rows_by_table["fact_compute_market_state"],
        )
    )

    for table_name, rows in rows_by_table.items():
        write_parquet_rows(table_refs[table_name], rows)

    benchmark_constituents = query_parquet(
        parquet_uri=table_refs["fact_gpu_listings"],
        table_name="fact_gpu_listings",
        sql=gold_model_sql("fact_benchmark_constituents", query_context),
    )
    rows_by_table["fact_benchmark_constituents"] = benchmark_constituents
    write_parquet_rows(
        table_refs["fact_benchmark_constituents"],
        benchmark_constituents,
    )
    benchmark_values = query_parquet(
        parquet_uri=table_refs["fact_benchmark_constituents"],
        table_name="fact_benchmark_constituents",
        sql=gold_model_sql("fact_benchmark_values", query_context),
    )
    rows_by_table["fact_benchmark_values"] = benchmark_values
    write_parquet_rows(table_refs["fact_benchmark_values"], benchmark_values)

    prime_frontier_rows, prime_frontier_refs = build_prime_frontier_gold_products(
        lake_root=lake_root,
        previous_gold_manifest=previous_gold_manifest,
        current_listing_rows=rows_by_table["fact_gpu_listings"],
        observed_date=observed_date,
        gold_run_id=gold_run_id,
        benchmark_values_ref=table_refs["fact_benchmark_values"],
    )
    rows_by_table.update(prime_frontier_rows)
    table_refs.update(prime_frontier_refs)
    for table_name in PRIME_FRONTIER_GOLD_TABLES:
        rows_by_table.setdefault(table_name, [])

    row_counts = {table_name: len(rows) for table_name, rows in rows_by_table.items()}
    executed_gold_models = [*CORE_GOLD_SQL_TABLES]
    if "fact_prime_frontier_offer_reference_history" in table_refs:
        executed_gold_models.append("fact_prime_frontier_offer_reference_history")
    if "fact_prime_frontier_offer_ladder" in table_refs:
        executed_gold_models.append("fact_prime_frontier_offer_ladder")
    executed_gold_models.extend(
        ["fact_benchmark_values", "fact_benchmark_constituents"]
    )
    sql_models = gold_sql_models(
        executed_gold_models,
        methodology_versions={
            "fact_compute_market_state": MARKET_STATE_METHODOLOGY_VERSION,
            "fact_prime_frontier_offer_reference_history": (
                PRIME_FRONTIER_METHOD_VERSION
            ),
            "fact_prime_frontier_offer_ladder": PRIME_FRONTIER_METHOD_VERSION,
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
    table_refs: dict[str, str],
    row_counts: dict[str, int],
    sql_models: dict[str, dict[str, str]] | None = None,
) -> str:
    manifest_ref = gold_manifest_ref(
        lake_root, observed_date=observed_date, run_id=run_id
    )
    payload = {
        "manifest_version": GOLD_MANIFEST_VERSION,
        "table": GOLD_MANIFEST_TABLE,
        "methodology_version": GOLD_METHODOLOGY_VERSION,
        "provider_scope": provider_scope,
        "run_id": run_id,
        "observed_at": utc_now().isoformat(),
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
