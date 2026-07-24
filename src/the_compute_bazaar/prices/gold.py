"""Build Curia-authored gold market tables from normalized GPU offers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .benchmark_queries import (
    BENCHMARK_FAMILIES,
    BENCHMARK_METHODOLOGY_VERSION,
    benchmark_constituents_v0_sql,
    benchmark_values_v0_sql,
)
from .datafusion import query_parquet, query_tables
from .manifest import read_latest_manifest
from .schemas import to_jsonable, utc_now
from .storage import (
    list_refs,
    read_json,
    table_partition,
    write_json,
    write_parquet_rows,
)


GOLD_MANIFEST_TABLE = "gold_market"
GOLD_MANIFEST_VERSION = "v1"
GOLD_METHODOLOGY_VERSION = "gold_gpu_market_v1"

GOLD_TABLES = {
    "fact_gpu_listings": "listings.parquet",
    "dim_gpu_products": "gpu_products.parquet",
    "dim_providers": "providers.parquet",
    "dim_regions": "regions.parquet",
    "fact_price_index_values": "price_index_values.parquet",
    "fact_index_constituents": "index_constituents.parquet",
    "fact_benchmark_values": "benchmark_values.parquet",
    "fact_benchmark_constituents": "benchmark_constituents.parquet",
}

FEATURED_INDEX_PRODUCTS = [
    {"gpu_model": "H100_80GB", "label": "H100"},
    {"gpu_model": "H200_141GB", "label": "H200"},
    {"gpu_model": "B200_180GB", "label": "B200"},
    {"gpu_model": "B300_288GB", "label": "B300"},
]


@dataclass(frozen=True)
class GoldBuildResult:
    run_id: str
    provider_scope: list[str]
    source_run_ids: dict[str, str]
    source_normalized_refs: dict[str, str]
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
    provider_scope = providers or [provider]
    source_manifests = {
        source_provider: read_latest_manifest(lake_root, provider=source_provider)
        for source_provider in provider_scope
    }
    source_normalized_refs: dict[str, str] = {}
    source_run_ids: dict[str, str] = {}
    for source_provider, manifest in source_manifests.items():
        normalized_ref = manifest.get("normalized_ref")
        if not normalized_ref:
            raise RuntimeError(
                f"Latest {source_provider} manifest has no normalized_ref"
            )
        source_normalized_refs[source_provider] = str(normalized_ref)
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
        "calculated_at": utc_now().isoformat(),
    }

    tables = {
        f"silver_gpu_offers_{index}": source_normalized_refs[source_provider]
        for index, source_provider in enumerate(provider_scope)
    }
    silver_source_cte = _silver_source_cte(list(tables))
    rows_by_table = {
        "fact_gpu_listings": query_tables(
            tables=tables, sql=_fact_gpu_listings_sql(query_context, silver_source_cte)
        ),
        "dim_gpu_products": query_tables(
            tables=tables, sql=_dim_gpu_products_sql(query_context, silver_source_cte)
        ),
        "dim_providers": query_tables(
            tables=tables, sql=_dim_providers_sql(query_context, silver_source_cte)
        ),
        "dim_regions": query_tables(
            tables=tables, sql=_dim_regions_sql(query_context, silver_source_cte)
        ),
        "fact_price_index_values": query_tables(
            tables=tables,
            sql=_fact_price_index_values_sql(query_context, silver_source_cte),
        ),
        "fact_index_constituents": query_tables(
            tables=tables,
            sql=_fact_index_constituents_sql(query_context, silver_source_cte),
        ),
    }

    for table_name, rows in rows_by_table.items():
        write_parquet_rows(table_refs[table_name], rows)

    benchmark_values, benchmark_constituents = _benchmark_rows_from_listing_ref(
        table_refs["fact_gpu_listings"],
        context=query_context,
    )
    rows_by_table["fact_benchmark_values"] = benchmark_values
    rows_by_table["fact_benchmark_constituents"] = benchmark_constituents

    for table_name in ["fact_benchmark_values", "fact_benchmark_constituents"]:
        rows = rows_by_table[table_name]
        write_parquet_rows(table_refs[table_name], rows)

    row_counts = {table_name: len(rows) for table_name, rows in rows_by_table.items()}
    manifest_ref = write_gold_manifest(
        lake_root=lake_root,
        provider_scope=provider_scope,
        run_id=gold_run_id,
        observed_date=observed_date,
        source_manifests=source_manifests,
        table_refs=table_refs,
        row_counts=row_counts,
    )

    return GoldBuildResult(
        run_id=gold_run_id,
        provider_scope=provider_scope,
        source_run_ids=source_run_ids,
        source_normalized_refs=source_normalized_refs,
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
        "table_refs": table_refs,
        "row_counts": row_counts,
        "manifest_ref": manifest_ref,
    }
    write_json(manifest_ref, payload)
    write_json(latest_gold_manifest_ref(lake_root), payload)
    return manifest_ref


def latest_gold_manifest_ref(lake_root: str) -> str:
    return "/".join(
        [lake_root.rstrip("/"), "_manifests", GOLD_MANIFEST_TABLE, "latest.json"]
    )


def gold_manifest_ref(lake_root: str, *, observed_date: str, run_id: str) -> str:
    return "/".join(
        [
            lake_root.rstrip("/"),
            "_manifests",
            GOLD_MANIFEST_TABLE,
            f"date={observed_date}",
            f"run_id={run_id}.json",
        ]
    )


def read_latest_gold_manifest(lake_root: str) -> dict[str, Any]:
    return dict(read_json(latest_gold_manifest_ref(lake_root)))


def list_gold_manifests(lake_root: str, *, limit: int = 48) -> list[dict[str, Any]]:
    requested_limit = max(1, int(limit))
    refs = [
        ref
        for ref in list_refs(gold_manifest_prefix(lake_root), suffix=".json")
        if "/run_id=" in ref or "/run_id%3D" in ref
    ]
    manifests: list[dict[str, Any]] = []
    for ref in reversed(refs):
        try:
            manifest = dict(read_json(ref))
        except Exception:  # noqa: BLE001 - one bad manifest should not hide the usable history.
            continue
        if manifest.get("table_refs", {}).get("fact_price_index_values"):
            manifests.append(manifest)
        if len(manifests) >= requested_limit:
            break

    manifests.sort(key=lambda row: str(row.get("observed_at") or ""), reverse=True)
    return manifests[:requested_limit]


def gold_manifest_prefix(lake_root: str) -> str:
    return "/".join([lake_root.rstrip("/"), "_manifests", GOLD_MANIFEST_TABLE])


def query_gold_price_index(
    *, lake_root: str, limit: int | None = None
) -> dict[str, Any]:
    manifest = read_latest_gold_manifest(lake_root)
    table_ref = manifest["table_refs"]["fact_price_index_values"]
    sql = """
select *
from fact_price_index_values
order by floor_usd_gpu_hr asc, offer_count desc
"""
    rows = query_parquet(
        parquet_uri=table_ref,
        table_name="fact_price_index_values",
        sql=_with_limit(sql, limit),
    )
    return {"manifest": manifest, "rows": rows}


def query_gold_index_history(
    *,
    lake_root: str,
    history_limit: int = 48,
    gpu_models: list[str] | None = None,
) -> dict[str, Any]:
    manifests = list_gold_manifests(lake_root, limit=history_limit)
    filters = ""
    if gpu_models:
        values = ", ".join(_sql_literal(model) for model in gpu_models)
        filters = f"where gpu_model in ({values})"

    rows: list[dict[str, Any]] = []
    for manifest in reversed(manifests):
        table_ref = manifest["table_refs"]["fact_price_index_values"]
        sql = f"""
select
  index_symbol,
  gpu_product_id,
  gpu_model,
  methodology_version,
  floor_usd_gpu_hr,
  simple_mean_usd_gpu_hr,
  cheapest_offer_usd_hr,
  offer_count,
  provider_count,
  country_count,
  latest_observed_at,
  calculated_at
from fact_price_index_values
{filters}
order by gpu_model, floor_usd_gpu_hr asc
"""
        for row in query_parquet(
            parquet_uri=table_ref,
            table_name="fact_price_index_values",
            sql=sql,
        ):
            rows.append(
                {
                    **row,
                    "gold_run_id": manifest.get("run_id"),
                    "gold_observed_at": manifest.get("observed_at"),
                    "gold_observed_date": manifest.get("observed_date"),
                    "provider_scope": manifest.get("provider_scope"),
                    "source_run_ids": manifest.get("source_run_ids"),
                }
            )

    rows.sort(
        key=lambda row: (
            str(row.get("gold_observed_at") or ""),
            str(row.get("gpu_model") or ""),
        )
    )
    return {
        "manifest": read_latest_gold_manifest(lake_root),
        "history_manifest_count": len(manifests),
        "rows": rows,
    }


def query_gold_featured_index(
    *,
    lake_root: str,
    products: list[dict[str, str]] | None = None,
    history_limit: int = 48,
) -> dict[str, Any]:
    """Return a stable frontier GPU floor strip for product/story surfaces."""
    manifest = read_latest_gold_manifest(lake_root)
    featured_products = products or FEATURED_INDEX_PRODUCTS
    gpu_models = [product["gpu_model"] for product in featured_products]
    values = ", ".join(_sql_literal(model) for model in gpu_models)
    table_ref = manifest["table_refs"]["fact_price_index_values"]
    latest_rows = query_parquet(
        parquet_uri=table_ref,
        table_name="fact_price_index_values",
        sql=f"""
select
  index_symbol,
  gpu_product_id,
  gpu_model,
  methodology_version,
  floor_usd_gpu_hr,
  simple_mean_usd_gpu_hr,
  cheapest_offer_usd_hr,
  offer_count,
  provider_count,
  country_count,
  latest_observed_at,
  calculated_at
from fact_price_index_values
where gpu_model in ({values})
order by gpu_model
""",
    )
    latest_by_model = {str(row.get("gpu_model")): row for row in latest_rows}

    warnings: list[str] = []
    try:
        history = query_gold_index_history(
            lake_root=lake_root,
            history_limit=history_limit,
            gpu_models=gpu_models,
        )
        history_rows = history["rows"]
        history_manifest_count = history["history_manifest_count"]
    except Exception as exc:  # noqa: BLE001 - featured values should still publish without history.
        history_rows = []
        history_manifest_count = 0
        warnings.append(f"featured index history skipped: {exc}")

    last_seen_by_model: dict[str, dict[str, Any]] = {}
    for row in history_rows:
        gpu_model = str(row.get("gpu_model") or "")
        if gpu_model:
            last_seen_by_model[gpu_model] = row

    rows = []
    for product in featured_products:
        gpu_model = product["gpu_model"]
        label = product.get("label") or gpu_model
        latest = latest_by_model.get(gpu_model)
        last_seen = last_seen_by_model.get(gpu_model)
        if latest:
            rows.append(
                {
                    **latest,
                    "label": label,
                    "status": "observed_latest",
                    "is_latest": True,
                    "gold_run_id": manifest.get("run_id"),
                    "gold_observed_at": manifest.get("observed_at"),
                    "gold_observed_date": manifest.get("observed_date"),
                    "provider_scope": manifest.get("provider_scope"),
                    "source_run_ids": manifest.get("source_run_ids"),
                    "last_seen_floor_usd_gpu_hr": latest.get("floor_usd_gpu_hr"),
                    "last_seen_at": manifest.get("observed_at"),
                    "last_seen_gold_run_id": manifest.get("run_id"),
                }
            )
            continue

        if last_seen:
            rows.append(
                {
                    **last_seen,
                    "label": label,
                    "status": "not_present_latest",
                    "is_latest": False,
                    "floor_usd_gpu_hr": None,
                    "current_gold_run_id": manifest.get("run_id"),
                    "current_gold_observed_at": manifest.get("observed_at"),
                    "gold_observed_date": manifest.get("observed_date"),
                    "last_seen_floor_usd_gpu_hr": last_seen.get("floor_usd_gpu_hr"),
                    "last_seen_at": last_seen.get("gold_observed_at")
                    or last_seen.get("latest_observed_at"),
                    "last_seen_gold_run_id": last_seen.get("gold_run_id"),
                }
            )
            continue

        rows.append(
            {
                "label": label,
                "gpu_model": gpu_model,
                "gpu_product_id": gpu_model,
                "status": "not_seen",
                "is_latest": False,
                "floor_usd_gpu_hr": None,
                "last_seen_floor_usd_gpu_hr": None,
                "last_seen_at": None,
                "gold_run_id": manifest.get("run_id"),
                "gold_observed_at": manifest.get("observed_at"),
                "gold_observed_date": manifest.get("observed_date"),
                "provider_scope": manifest.get("provider_scope"),
                "source_run_ids": manifest.get("source_run_ids"),
            }
        )

    return {
        "manifest": manifest,
        "history_manifest_count": history_manifest_count,
        "products": featured_products,
        "rows": rows,
        "warnings": warnings,
    }


def query_gold_benchmark_values(
    *, lake_root: str, limit: int | None = None
) -> dict[str, Any]:
    manifest = read_latest_gold_manifest(lake_root)
    table_ref = manifest["table_refs"].get("fact_benchmark_values")
    if not table_ref:
        values, _ = _benchmark_rows_from_latest_listings(manifest)
        return {"manifest": manifest, "rows": values[:limit] if limit else values}

    sql = """
select *
from fact_benchmark_values
order by benchmark_family_id
"""
    rows = query_parquet(
        parquet_uri=table_ref,
        table_name="fact_benchmark_values",
        sql=_with_limit(sql, limit),
    )
    return {"manifest": manifest, "rows": rows}


def query_gold_benchmark_history(
    *,
    lake_root: str,
    history_limit: int = 24,
) -> dict[str, Any]:
    """Return recent frontier benchmark values as a compact time series."""
    manifests = list_gold_manifests(lake_root, limit=history_limit)
    rows: list[dict[str, Any]] = []
    included_manifest_count = 0

    for manifest in reversed(manifests):
        try:
            table_ref = manifest.get("table_refs", {}).get("fact_benchmark_values")
            if table_ref:
                benchmark_rows = query_parquet(
                    parquet_uri=table_ref,
                    table_name="fact_benchmark_values",
                    sql="""
select *
from fact_benchmark_values
order by benchmark_family_id
""",
                )
            else:
                benchmark_rows, _ = _benchmark_rows_from_latest_listings(manifest)
        except Exception:  # noqa: BLE001 - one legacy run should not hide comparable history.
            continue

        benchmark_rows = [
            row
            for row in benchmark_rows
            if row.get("methodology_version") == BENCHMARK_METHODOLOGY_VERSION
        ]
        if not benchmark_rows:
            continue
        included_manifest_count += 1

        for row in benchmark_rows:
            rows.append(
                {
                    **row,
                    "gold_run_id": manifest.get("run_id"),
                    "gold_observed_at": manifest.get("observed_at"),
                    "gold_observed_date": manifest.get("observed_date"),
                }
            )

    rows.sort(
        key=lambda row: (
            str(row.get("gold_observed_at") or ""),
            str(row.get("benchmark_family_id") or ""),
        )
    )
    return {
        "manifest": read_latest_gold_manifest(lake_root),
        "history_manifest_count": included_manifest_count,
        "rows": rows,
    }


def query_gold_benchmark_constituents(
    *,
    lake_root: str,
    benchmark_family_id: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    manifest = read_latest_gold_manifest(lake_root)
    table_ref = manifest["table_refs"].get("fact_benchmark_constituents")
    if not table_ref:
        _, constituents = _benchmark_rows_from_latest_listings(manifest)
        rows = [
            row
            for row in constituents
            if benchmark_family_id is None
            or row.get("benchmark_family_id") == benchmark_family_id
        ]
        return {"manifest": manifest, "rows": rows[:limit] if limit else rows}

    filters = ""
    if benchmark_family_id:
        filters = f"where benchmark_family_id = {_sql_literal(benchmark_family_id)}"
    sql = f"""
select *
from fact_benchmark_constituents
{filters}
order by benchmark_family_id, included desc, constituent_rank asc, price_usd_gpu_hr asc
"""
    rows = query_parquet(
        parquet_uri=table_ref,
        table_name="fact_benchmark_constituents",
        sql=_with_limit(sql, limit),
    )
    return {"manifest": manifest, "rows": rows}


def query_gold_provider_comparison(
    *,
    lake_root: str,
    gpu_model: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    manifest = read_latest_gold_manifest(lake_root)
    table_ref = manifest["table_refs"]["fact_gpu_listings"]
    filters = ["availability_status in ('available', 'published_rate')"]
    if gpu_model:
        filters.append(f"gpu_model = {_sql_literal(gpu_model)}")
    where = f"where {' and '.join(filters)}"
    sql = f"""
select
  gpu_model,
  provider,
  min(price_usd_gpu_hr) as floor_usd_gpu_hr,
  avg(price_usd_gpu_hr) as simple_mean_usd_gpu_hr,
  min(price_usd_hr) as cheapest_offer_usd_hr,
  count(*) as listing_count,
  count(distinct country) as country_count,
  max(observed_at) as latest_observed_at
from fact_gpu_listings
{where}
group by gpu_model, provider
order by gpu_model, floor_usd_gpu_hr asc
"""
    rows = query_parquet(
        parquet_uri=table_ref,
        table_name="fact_gpu_listings",
        sql=_with_limit(sql, limit),
    )
    return {"manifest": manifest, "rows": rows}


def query_gold_listings(
    *,
    lake_root: str,
    gpu_model: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    manifest = read_latest_gold_manifest(lake_root)
    table_ref = manifest["table_refs"]["fact_gpu_listings"]
    filters = ["availability_status in ('available', 'published_rate')"]
    if gpu_model:
        filters.append(f"gpu_model = {_sql_literal(gpu_model)}")
    where = f"where {' and '.join(filters)}"
    sql = f"""
select
  listing_id,
  provider_id,
  gpu_model,
  gpu_product_id,
  provider,
  source_connector,
  price_usd_gpu_hr,
  price_usd_instance_hr,
  gpu_count,
  available_gpu_count,
  vram_gb,
  country,
  region,
  is_spot,
  is_secure,
  availability_status,
  freshness_status,
  has_raw_evidence,
  source_offer_id,
  source_run_id,
  observed_at
from fact_gpu_listings
{where}
order by price_usd_gpu_hr asc, price_usd_hr asc
"""
    rows = query_parquet(
        parquet_uri=table_ref,
        table_name="fact_gpu_listings",
        sql=_with_limit(sql, limit),
    )
    return {"manifest": manifest, "rows": rows}


def query_gold_index_constituents(
    *,
    lake_root: str,
    gpu_model: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    manifest = read_latest_gold_manifest(lake_root)
    table_ref = manifest["table_refs"]["fact_index_constituents"]
    filters = []
    if gpu_model:
        filters.append(f"gpu_model = {_sql_literal(gpu_model)}")
    where = f"where {' and '.join(filters)}" if filters else ""
    sql = f"""
select
  index_symbol,
  gpu_model,
  listing_id,
  provider,
  price_usd_gpu_hr,
  included,
  exclusion_reason,
  constituent_rank,
  is_floor_constituent,
  observed_at
from fact_index_constituents
{where}
order by gpu_model, included desc, constituent_rank asc, price_usd_gpu_hr asc
"""
    rows = query_parquet(
        parquet_uri=table_ref,
        table_name="fact_index_constituents",
        sql=_with_limit(sql, limit),
    )
    return {"manifest": manifest, "rows": rows}


def query_gold_index_quality(
    *, lake_root: str, limit: int | None = None
) -> dict[str, Any]:
    manifest = read_latest_gold_manifest(lake_root)
    table_ref = manifest["table_refs"]["fact_index_constituents"]
    sql = """
select
  gpu_model,
  count(*) as candidate_count,
  sum(case when included then 1 else 0 end) as included_count,
  sum(case when not included then 1 else 0 end) as excluded_count,
  count(distinct provider) as provider_count,
  min(case when included then price_usd_gpu_hr else null end) as floor_usd_gpu_hr,
  max(observed_at) as latest_observed_at
from fact_index_constituents
group by gpu_model
order by included_count desc, candidate_count desc, gpu_model
"""
    rows = query_parquet(
        parquet_uri=table_ref,
        table_name="fact_index_constituents",
        sql=_with_limit(sql, limit),
    )
    return {"manifest": manifest, "rows": rows}


def export_gold_dashboard_snapshot(
    *,
    lake_root: str,
    output_root: str,
    limit: int = 100,
) -> dict[str, Any]:
    """Export public JSON snapshots for static D3/blog consumers."""
    manifest = read_latest_gold_manifest(lake_root)
    public_manifest = _public_gold_manifest(
        manifest,
        dashboard_exported_at=utc_now().isoformat(),
        dashboard_output_root=output_root,
    )
    warnings = []
    index = query_gold_price_index(lake_root=lake_root, limit=limit)["rows"]
    featured_index_payload = query_gold_featured_index(
        lake_root=lake_root, history_limit=12
    )
    warnings.extend(featured_index_payload.get("warnings", []))
    featured_index = featured_index_payload["rows"]
    benchmark_values_payload = query_gold_benchmark_values(lake_root=lake_root)
    benchmark_values = benchmark_values_payload["rows"]
    # Benchmark evidence is a complete audit surface, not a sampled dashboard table.
    benchmark_constituents = query_gold_benchmark_constituents(lake_root=lake_root)[
        "rows"
    ]
    public_benchmark_values = [_public_benchmark_value(row) for row in benchmark_values]
    public_benchmark_constituents = [
        _public_benchmark_constituent(row) for row in benchmark_constituents
    ]
    try:
        benchmark_history_payload = query_gold_benchmark_history(
            lake_root=lake_root, history_limit=24
        )
    except Exception as exc:  # noqa: BLE001 - latest values should survive a history failure.
        benchmark_history_payload = {"history_manifest_count": 0, "rows": []}
        warnings.append(f"benchmark history export skipped: {exc}")
    public_benchmark_history = [
        _public_benchmark_history_value(row)
        for row in benchmark_history_payload["rows"]
    ]
    try:
        index_history_payload = query_gold_index_history(
            lake_root=lake_root, history_limit=24
        )
    except Exception as exc:  # noqa: BLE001 - latest dashboard snapshots are more important than history.
        index_history_payload = {"history_manifest_count": 0, "rows": []}
        warnings.append(f"index history export skipped: {exc}")
    index_history = index_history_payload["rows"]
    provider_comparison = query_gold_provider_comparison(
        lake_root=lake_root, limit=limit
    )["rows"]
    listings = query_gold_listings(lake_root=lake_root, limit=limit)["rows"]
    try:
        constituents = query_gold_index_constituents(lake_root=lake_root, limit=limit)[
            "rows"
        ]
        index_quality = query_gold_index_quality(lake_root=lake_root, limit=limit)[
            "rows"
        ]
    except Exception as exc:  # noqa: BLE001 - old gold tables may not have the quality columns yet.
        constituents = []
        index_quality = []
        warnings.append(f"index constituent export skipped: {exc}")

    output_refs = {
        "manifest": "/".join([output_root.rstrip("/"), "manifest.json"]),
        "latest_index": "/".join([output_root.rstrip("/"), "latest-index.json"]),
        "featured_index": "/".join([output_root.rstrip("/"), "featured-index.json"]),
        "featured_benchmarks": "/".join(
            [output_root.rstrip("/"), "featured-benchmarks.json"]
        ),
        "benchmark_history": "/".join(
            [output_root.rstrip("/"), "benchmark-history.json"]
        ),
        "index_constituents": "/".join(
            [output_root.rstrip("/"), "index-constituents.json"]
        ),
        "index_quality": "/".join([output_root.rstrip("/"), "index-quality.json"]),
        "index_history": "/".join([output_root.rstrip("/"), "index-history.json"]),
        "benchmark_constituents": "/".join(
            [output_root.rstrip("/"), "benchmark-constituents.json"]
        ),
        "provider_comparison": "/".join(
            [output_root.rstrip("/"), "provider-comparison.json"]
        ),
        "listings_sample": "/".join([output_root.rstrip("/"), "listings-sample.json"]),
    }
    write_json(output_refs["manifest"], public_manifest)
    write_json(
        output_refs["latest_index"], {"manifest": public_manifest, "rows": index}
    )
    write_json(
        output_refs["featured_index"],
        {
            "manifest": public_manifest,
            "history_manifest_count": featured_index_payload["history_manifest_count"],
            "products": featured_index_payload["products"],
            "rows": featured_index,
        },
    )
    write_json(
        output_refs["featured_benchmarks"],
        {
            "manifest": public_manifest,
            "methodology_version": BENCHMARK_METHODOLOGY_VERSION,
            "families": BENCHMARK_FAMILIES,
            "rows": public_benchmark_values,
        },
    )
    write_json(
        output_refs["benchmark_history"],
        {
            "manifest": public_manifest,
            "methodology_version": BENCHMARK_METHODOLOGY_VERSION,
            "families": BENCHMARK_FAMILIES,
            "history_manifest_count": benchmark_history_payload[
                "history_manifest_count"
            ],
            "row_count": len(public_benchmark_history),
            "rows": public_benchmark_history,
        },
    )
    write_json(
        output_refs["index_constituents"],
        {"manifest": public_manifest, "rows": constituents},
    )
    write_json(
        output_refs["index_quality"],
        {"manifest": public_manifest, "rows": index_quality},
    )
    write_json(
        output_refs["index_history"],
        {
            "manifest": public_manifest,
            "history_manifest_count": index_history_payload["history_manifest_count"],
            "row_count": len(index_history),
            "rows": index_history,
        },
    )
    write_json(
        output_refs["benchmark_constituents"],
        {
            "manifest": public_manifest,
            "methodology_version": BENCHMARK_METHODOLOGY_VERSION,
            "complete": True,
            "row_count": len(public_benchmark_constituents),
            "rows": public_benchmark_constituents,
        },
    )
    write_json(
        output_refs["provider_comparison"],
        {"manifest": public_manifest, "rows": provider_comparison},
    )
    write_json(
        output_refs["listings_sample"], {"manifest": public_manifest, "rows": listings}
    )

    return {
        "output_refs": output_refs,
        "row_counts": {
            "latest_index": len(index),
            "featured_index": len(featured_index),
            "featured_benchmarks": len(benchmark_values),
            "benchmark_history": len(public_benchmark_history),
            "index_constituents": len(constituents),
            "index_quality": len(index_quality),
            "index_history": len(index_history),
            "benchmark_constituents": len(benchmark_constituents),
            "provider_comparison": len(provider_comparison),
            "listings_sample": len(listings),
        },
        "source_gold_manifest_ref": manifest.get("manifest_ref"),
        "warnings": warnings,
    }


def _fact_gpu_listings_sql(context: dict[str, str], silver_source_cte: str) -> str:
    return f"""
with {silver_source_cte}
select
  concat(provider, ':', source_offer_id) as listing_id,
  provider as provider_id,
  provider,
  source_offer_id,
  gpu_model as gpu_product_id,
  gpu_model,
  gpu_raw_name,
  source_connector,
  gpu_count,
  available_gpu_count,
  vram_gb,
  price_usd_hr,
  price_usd_hr as price_usd_instance_hr,
  case
    when gpu_count is not null and gpu_count > 0 then price_usd_hr / gpu_count
    else price_usd_hr
  end as price_usd_gpu_hr,
  currency,
  country,
  region,
  case
    when country is null and region is null then 'unknown'
    else concat(coalesce(country, 'unknown'), ':', coalesce(region, 'unknown'))
  end as region_id,
  is_spot,
  is_secure,
  availability_status,
  'fresh' as freshness_status,
  observed_at,
  raw_ref,
  raw_ref is not null as has_raw_evidence,
  {_sql_literal(context["source_run_id"])} as source_run_id,
  {_sql_literal(context["source_manifest_ref"])} as source_manifest_ref,
  {_sql_literal(context["source_normalized_ref"])} as source_normalized_ref,
  {_sql_literal(context["calculated_at"])} as calculated_at
from silver_gpu_offers
where price_usd_hr > 0
"""


def _dim_gpu_products_sql(context: dict[str, str], silver_source_cte: str) -> str:
    return f"""
with {silver_source_cte},
usable_offers as (
  select *
  from silver_gpu_offers
  where price_usd_hr > 0
)
select
  gpu_model as gpu_product_id,
  gpu_model,
  max(vram_gb) as max_vram_gb,
  min(gpu_count) as min_gpu_count,
  max(gpu_count) as max_gpu_count,
  count(*) as listing_count,
  count(distinct provider) as provider_count,
  min(price_usd_hr / case when gpu_count > 0 then gpu_count else 1 end) as floor_usd_gpu_hr,
  max(observed_at) as latest_observed_at,
  {_sql_literal(context["source_run_id"])} as source_run_id,
  {_sql_literal(context["calculated_at"])} as calculated_at
from usable_offers
group by gpu_model
order by floor_usd_gpu_hr asc, listing_count desc
"""


def _dim_providers_sql(context: dict[str, str], silver_source_cte: str) -> str:
    return f"""
with {silver_source_cte}
select
  provider as provider_id,
  provider,
  count(*) as listing_count,
  count(distinct source_connector) as source_connector_count,
  count(distinct gpu_model) as gpu_product_count,
  count(distinct country) as country_count,
  min(price_usd_hr / case when gpu_count > 0 then gpu_count else 1 end) as floor_usd_gpu_hr,
  max(observed_at) as latest_observed_at,
  {_sql_literal(context["source_run_id"])} as source_run_id,
  {_sql_literal(context["calculated_at"])} as calculated_at
from silver_gpu_offers
where price_usd_hr > 0
group by provider
order by provider
"""


def _dim_regions_sql(context: dict[str, str], silver_source_cte: str) -> str:
    return f"""
with {silver_source_cte}
select
  case
    when country is null and region is null then 'unknown'
    else concat(coalesce(country, 'unknown'), ':', coalesce(region, 'unknown'))
  end as region_id,
  country,
  region,
  count(*) as listing_count,
  count(distinct provider) as provider_count,
  count(distinct gpu_model) as gpu_product_count,
  min(price_usd_hr / case when gpu_count > 0 then gpu_count else 1 end) as floor_usd_gpu_hr,
  max(observed_at) as latest_observed_at,
  {_sql_literal(context["source_run_id"])} as source_run_id,
  {_sql_literal(context["calculated_at"])} as calculated_at
from silver_gpu_offers
where price_usd_hr > 0
group by country, region
order by listing_count desc, region_id
"""


def _fact_price_index_values_sql(
    context: dict[str, str], silver_source_cte: str
) -> str:
    return f"""
with {silver_source_cte},
usable_offers as (
  select
    provider,
    gpu_model,
    source_offer_id,
    observed_at,
    price_usd_hr,
    case
      when gpu_count is not null and gpu_count > 0 then price_usd_hr / gpu_count
      else price_usd_hr
    end as price_usd_gpu_hr,
    country,
    is_spot,
    is_secure
  from silver_gpu_offers
  where price_usd_hr > 0
    and availability_status in ('available', 'published_rate')
)
select
  concat('CBZ-GPU-FLOOR-', gpu_model) as index_symbol,
  gpu_model as gpu_product_id,
  gpu_model,
  'floor_v1' as methodology_version,
  min(price_usd_gpu_hr) as floor_usd_gpu_hr,
  avg(price_usd_gpu_hr) as simple_mean_usd_gpu_hr,
  min(price_usd_hr) as cheapest_offer_usd_hr,
  count(*) as offer_count,
  count(distinct provider) as provider_count,
  count(distinct country) as country_count,
  sum(case when coalesce(is_secure, false) then 1 else 0 end) as secure_offer_count,
  sum(case when coalesce(is_spot, false) then 1 else 0 end) as spot_offer_count,
  max(observed_at) as latest_observed_at,
  {_sql_literal(context["source_run_id"])} as source_run_id,
  {_sql_literal(context["calculated_at"])} as calculated_at
from usable_offers
group by gpu_model
order by floor_usd_gpu_hr asc, offer_count desc
"""


def _fact_index_constituents_sql(
    context: dict[str, str], silver_source_cte: str
) -> str:
    return f"""
with {silver_source_cte},
candidate_offers as (
  select
    concat(provider, ':', source_offer_id) as listing_id,
    provider,
    source_connector,
    source_offer_id,
    gpu_model,
    available_gpu_count,
    price_usd_hr,
    case
      when gpu_count is not null and gpu_count > 0 then price_usd_hr / gpu_count
      else price_usd_hr
    end as price_usd_gpu_hr,
    country,
    region,
    availability_status,
    case
      when price_usd_hr is null or price_usd_hr <= 0 then false
      when availability_status not in ('available', 'published_rate') then false
      else true
    end as included,
    case
      when price_usd_hr is null or price_usd_hr <= 0 then 'non_positive_price'
      when availability_status not in ('available', 'published_rate') then 'not_available'
      else null
    end as exclusion_reason,
    observed_at
  from silver_gpu_offers
),
ranked as (
  select
    *,
    case
      when included then row_number() over(partition by gpu_model, included order by price_usd_gpu_hr asc, price_usd_hr asc)
      else null
    end as constituent_rank
  from candidate_offers
)
select
  concat('CBZ-GPU-FLOOR-', gpu_model, ':', {_sql_literal(context["source_run_id"])}) as index_value_id,
  concat('CBZ-GPU-FLOOR-', gpu_model) as index_symbol,
  gpu_model as gpu_product_id,
  gpu_model,
  listing_id,
  provider,
  source_connector,
  source_offer_id,
  price_usd_hr,
  price_usd_gpu_hr,
  available_gpu_count,
  country,
  region,
  availability_status,
  included,
  exclusion_reason,
  observed_at,
  constituent_rank,
  included and constituent_rank = 1 as is_floor_constituent,
  {_sql_literal(context["source_run_id"])} as source_run_id,
  {_sql_literal(context["source_manifest_ref"])} as source_manifest_ref,
  {_sql_literal(context["source_normalized_ref"])} as source_normalized_ref,
  {_sql_literal(context["calculated_at"])} as calculated_at
from ranked
order by gpu_model, included desc, constituent_rank asc, price_usd_gpu_hr asc
"""


def _benchmark_rows_from_latest_listings(
    manifest: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    table_ref = manifest["table_refs"]["fact_gpu_listings"]
    context = {
        "source_run_id": ",".join(
            f"{name}:{run_id}"
            for name, run_id in dict(manifest.get("source_run_ids") or {}).items()
        ),
        "source_manifest_ref": ",".join(
            str(value)
            for value in dict(manifest.get("source_manifest_refs") or {}).values()
        ),
        "source_normalized_ref": ",".join(
            str(value)
            for value in dict(manifest.get("source_normalized_refs") or {}).values()
        ),
        "calculated_at": str(manifest.get("observed_at") or utc_now().isoformat()),
    }
    return _benchmark_rows_from_listing_ref(table_ref, context=context)


def _benchmark_rows_from_listing_ref(
    table_ref: str,
    *,
    context: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    values = query_parquet(
        parquet_uri=table_ref,
        table_name="fact_gpu_listings",
        sql=benchmark_values_v0_sql(context),
    )
    constituents = query_parquet(
        parquet_uri=table_ref,
        table_name="fact_gpu_listings",
        sql=benchmark_constituents_v0_sql(context),
    )
    return values, constituents


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


def _silver_source_cte(table_names: list[str]) -> str:
    columns = """
      provider,
      source_offer_id,
      observed_at,
      gpu_raw_name,
      gpu_model,
      coalesce(source_connector, provider) as source_connector,
      gpu_count,
      available_gpu_count,
      vram_gb,
      price_usd_hr,
      currency,
      country,
      region,
      is_spot,
      is_secure,
      availability_status,
      raw_ref
    """
    selects = [f"select {columns} from {table_name}" for table_name in table_names]
    return f"silver_gpu_offers as ({' union all '.join(selects)})"


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _with_limit(sql: str, limit: int | None) -> str:
    if limit is None:
        return sql
    return f"{sql.rstrip()}\nlimit {int(limit)}"


def _public_gold_manifest(
    manifest: dict[str, Any],
    *,
    dashboard_exported_at: str | None = None,
    dashboard_output_root: str | None = None,
) -> dict[str, Any]:
    return {
        "manifest_version": manifest.get("manifest_version"),
        "methodology_version": manifest.get("methodology_version"),
        "run_id": manifest.get("run_id"),
        "observed_at": manifest.get("observed_at"),
        "observed_date": manifest.get("observed_date"),
        "provider_scope": manifest.get("provider_scope"),
        "row_counts": manifest.get("row_counts"),
        "source_run_ids": manifest.get("source_run_ids"),
        "dashboard_exported_at": dashboard_exported_at,
        "dashboard_output_root": dashboard_output_root,
    }


def _public_benchmark_value(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: row.get(key)
        for key in [
            "benchmark_value_id",
            "benchmark_symbol",
            "benchmark_family_id",
            "benchmark_label",
            "gpu_model_prefixes",
            "methodology_version",
            "methodology_query_id",
            "benchmark_basis",
            "benchmark_usd_gpu_hr",
            "observed_average_usd_gpu_hr",
            "provider_floor_median_usd_gpu_hr",
            "provider_floor_mean_usd_gpu_hr",
            "provider_floor_p25_usd_gpu_hr",
            "provider_floor_p75_usd_gpu_hr",
            "floor_usd_gpu_hr",
            "median_usd_gpu_hr",
            "simple_mean_usd_gpu_hr",
            "trimmed_mean_usd_gpu_hr",
            "p25_usd_gpu_hr",
            "p75_usd_gpu_hr",
            "cheapest_offer_usd_hr",
            "offer_count",
            "included_offer_count",
            "provider_count",
            "gpu_model_count",
            "country_count",
            "secure_offer_count",
            "spot_offer_count",
            "latest_observed_at",
            "status",
            "source_run_id",
            "calculated_at",
        ]
    }


def _public_benchmark_history_value(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: row.get(key)
        for key in [
            "benchmark_symbol",
            "benchmark_family_id",
            "benchmark_label",
            "methodology_version",
            "benchmark_basis",
            "benchmark_usd_gpu_hr",
            "provider_floor_p25_usd_gpu_hr",
            "provider_floor_p75_usd_gpu_hr",
            "included_offer_count",
            "provider_count",
            "latest_observed_at",
            "calculated_at",
            "gold_run_id",
            "gold_observed_at",
            "gold_observed_date",
        ]
    }


def _public_benchmark_constituent(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: row.get(key)
        for key in [
            "benchmark_value_id",
            "benchmark_symbol",
            "benchmark_family_id",
            "benchmark_label",
            "methodology_version",
            "methodology_query_id",
            "listing_id",
            "provider",
            "source_connector",
            "source_offer_id",
            "gpu_model",
            "gpu_raw_name",
            "gpu_count",
            "available_gpu_count",
            "vram_gb",
            "price_usd_gpu_hr",
            "price_usd_instance_hr",
            "country",
            "region",
            "is_spot",
            "is_secure",
            "availability_status",
            "included",
            "inclusion_reason",
            "exclusion_reason",
            "constituent_rank",
            "provider_rank",
            "is_floor_constituent",
            "observed_at",
            "has_raw_evidence",
            "source_run_id",
            "calculated_at",
        ]
    }
