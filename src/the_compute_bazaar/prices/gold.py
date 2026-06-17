"""Build curated gold query tables from normalized GPU offers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .datafusion import query_parquet, query_tables
from .manifest import read_latest_manifest
from .schemas import to_jsonable, utc_now
from .storage import read_json, table_partition, write_json, write_parquet_rows


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
}


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
            raise RuntimeError(f"Latest {source_provider} manifest has no normalized_ref")
        source_normalized_refs[source_provider] = str(normalized_ref)
        source_run_ids[source_provider] = str(manifest["run_id"])

    observed_date = max(_observed_date(manifest) for manifest in source_manifests.values())
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
        "source_run_id": ",".join(f"{name}:{source_run_ids[name]}" for name in provider_scope),
        "source_manifest_ref": ",".join(
            str(source_manifests[name].get("manifest_ref") or "") for name in provider_scope
        ),
        "source_raw_ref": ",".join(str(source_manifests[name].get("raw_ref") or "") for name in provider_scope),
        "source_normalized_ref": ",".join(source_normalized_refs[name] for name in provider_scope),
        "calculated_at": utc_now().isoformat(),
    }

    tables = {
        f"silver_gpu_offers_{index}": source_normalized_refs[source_provider]
        for index, source_provider in enumerate(provider_scope)
    }
    silver_source_cte = _silver_source_cte(list(tables))
    rows_by_table = {
        "fact_gpu_listings": query_tables(tables=tables, sql=_fact_gpu_listings_sql(query_context, silver_source_cte)),
        "dim_gpu_products": query_tables(tables=tables, sql=_dim_gpu_products_sql(query_context, silver_source_cte)),
        "dim_providers": query_tables(tables=tables, sql=_dim_providers_sql(query_context, silver_source_cte)),
        "dim_regions": query_tables(tables=tables, sql=_dim_regions_sql(query_context, silver_source_cte)),
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
    manifest_ref = gold_manifest_ref(lake_root, observed_date=observed_date, run_id=run_id)
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
    return "/".join([lake_root.rstrip("/"), "_manifests", GOLD_MANIFEST_TABLE, "latest.json"])


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


def query_gold_price_index(*, lake_root: str, limit: int | None = None) -> dict[str, Any]:
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


def query_gold_provider_comparison(
    *,
    lake_root: str,
    gpu_model: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    manifest = read_latest_gold_manifest(lake_root)
    table_ref = manifest["table_refs"]["fact_gpu_listings"]
    filters = ["availability_status = 'available'"]
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
    filters = ["availability_status = 'available'"]
    if gpu_model:
        filters.append(f"gpu_model = {_sql_literal(gpu_model)}")
    where = f"where {' and '.join(filters)}"
    sql = f"""
select
  gpu_model,
  provider,
  price_usd_gpu_hr,
  price_usd_hr,
  gpu_count,
  country,
  region,
  availability_status,
  source_offer_id,
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


def export_gold_dashboard_snapshot(
    *,
    lake_root: str,
    output_root: str,
    limit: int = 100,
) -> dict[str, Any]:
    """Export public JSON snapshots for static D3/blog consumers."""
    manifest = read_latest_gold_manifest(lake_root)
    index = query_gold_price_index(lake_root=lake_root, limit=limit)["rows"]
    provider_comparison = query_gold_provider_comparison(lake_root=lake_root, limit=limit)["rows"]
    listings = query_gold_listings(lake_root=lake_root, limit=limit)["rows"]

    output_refs = {
        "manifest": "/".join([output_root.rstrip("/"), "manifest.json"]),
        "latest_index": "/".join([output_root.rstrip("/"), "latest-index.json"]),
        "provider_comparison": "/".join([output_root.rstrip("/"), "provider-comparison.json"]),
        "listings_sample": "/".join([output_root.rstrip("/"), "listings-sample.json"]),
    }
    write_json(output_refs["manifest"], _public_gold_manifest(manifest))
    write_json(output_refs["latest_index"], {"manifest": _public_gold_manifest(manifest), "rows": index})
    write_json(
        output_refs["provider_comparison"],
        {"manifest": _public_gold_manifest(manifest), "rows": provider_comparison},
    )
    write_json(output_refs["listings_sample"], {"manifest": _public_gold_manifest(manifest), "rows": listings})

    return {
        "output_refs": output_refs,
        "row_counts": {
            "latest_index": len(index),
            "provider_comparison": len(provider_comparison),
            "listings_sample": len(listings),
        },
        "source_gold_manifest_ref": manifest.get("manifest_ref"),
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
  gpu_count,
  vram_gb,
  price_usd_hr,
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


def _fact_price_index_values_sql(context: dict[str, str], silver_source_cte: str) -> str:
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
    and availability_status = 'available'
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


def _fact_index_constituents_sql(context: dict[str, str], silver_source_cte: str) -> str:
    return f"""
with {silver_source_cte},
usable_offers as (
  select
    concat(provider, ':', source_offer_id) as listing_id,
    provider,
    source_offer_id,
    gpu_model,
    price_usd_hr,
    case
      when gpu_count is not null and gpu_count > 0 then price_usd_hr / gpu_count
      else price_usd_hr
    end as price_usd_gpu_hr,
    country,
    region,
    observed_at
  from silver_gpu_offers
  where price_usd_hr > 0
    and availability_status = 'available'
),
ranked as (
  select
    *,
    row_number() over(partition by gpu_model order by price_usd_gpu_hr asc, price_usd_hr asc) as constituent_rank
  from usable_offers
)
select
  concat('CBZ-GPU-FLOOR-', gpu_model) as index_symbol,
  gpu_model as gpu_product_id,
  gpu_model,
  listing_id,
  provider,
  source_offer_id,
  price_usd_hr,
  price_usd_gpu_hr,
  country,
  region,
  observed_at,
  constituent_rank,
  constituent_rank = 1 as is_floor_constituent,
  {_sql_literal(context["source_run_id"])} as source_run_id,
  {_sql_literal(context["calculated_at"])} as calculated_at
from ranked
order by gpu_model, constituent_rank
"""


def _observed_date(manifest: dict[str, Any]) -> str:
    observed_at = str(manifest.get("observed_at") or "")
    if observed_at:
        normalized = observed_at.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized).astimezone(timezone.utc).date().isoformat()
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
      gpu_count,
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


def _public_gold_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "manifest_version": manifest.get("manifest_version"),
        "methodology_version": manifest.get("methodology_version"),
        "run_id": manifest.get("run_id"),
        "observed_at": manifest.get("observed_at"),
        "observed_date": manifest.get("observed_date"),
        "provider_scope": manifest.get("provider_scope"),
        "row_counts": manifest.get("row_counts"),
        "source_run_ids": manifest.get("source_run_ids"),
    }
