"""Read Gold market tables through DataFusion."""

from __future__ import annotations

from typing import Any

from .datafusion import DataFusionEngine
from .gold_manifest import (
    is_canonical_market_run_id,
    read_latest_gold_manifest,
)


def gpu_price_index_sql(
    *,
    table_name: str = "fact_gpu_price_index",
    family: str | None = None,
    history: bool = False,
) -> str:
    filters = (
        f"where benchmark_family_id = {_sql_literal(family.upper())}" if family else ""
    )
    if history:
        return f"""
select
  gold_observed_at,
  benchmark_family_id,
  benchmark_usd_gpu_hr,
  floor_usd_gpu_hr,
  provider_floor_p25_usd_gpu_hr,
  provider_floor_p75_usd_gpu_hr,
  included_offer_count,
  provider_count,
  gold_run_id
from {table_name}
{filters}
order by gold_observed_at, benchmark_family_id
"""
    return f"""
select
  benchmark_symbol,
  benchmark_family_id,
  benchmark_usd_gpu_hr,
  floor_usd_gpu_hr,
  provider_floor_p25_usd_gpu_hr,
  provider_floor_p75_usd_gpu_hr,
  offer_count,
  included_offer_count,
  provider_count,
  latest_observed_at,
  methodology_version as methodology
from {table_name}
{filters}
order by benchmark_family_id
"""


def gpu_availability_sql(
    *,
    table_name: str,
    gpu_model: str | None = None,
    measurement_kind: str | None = None,
) -> str:
    filters: list[str] = []
    if gpu_model:
        filters.append(_gpu_selector("resource_type", gpu_model))
    if measurement_kind:
        filters.append(f"measurement_kind = {_sql_literal(measurement_kind)}")
    where = f"where {' and '.join(filters)}" if filters else ""
    return f"""
select
  observation_id,
  observed_at,
  resource_type,
  provider,
  source_connector,
  measurement_kind,
  measurement_scope,
  unit,
  total_units,
  rented_units,
  available_units,
  rented_share,
  available_share,
  stock_status,
  count_precision,
  methodology_version as methodology
from {table_name}
{where}
order by observed_at desc, measurement_kind, provider, resource_type
"""


def provider_comparison_sql(
    *,
    table_name: str = "fact_gpu_listings",
    gpu_model: str | None = None,
) -> str:
    filters = ["source_availability_status in ('available', 'published_rate')"]
    if gpu_model:
        filters.append(_gpu_selector("gpu_model", gpu_model))
    return f"""
select
  gpu_model,
  provider,
  min(price_usd_gpu_hr) as floor_usd_gpu_hr,
  avg(price_usd_gpu_hr) as simple_mean_usd_gpu_hr,
  min(price_usd_instance_hr) as cheapest_offer_usd_instance_hr,
  count(*) as listing_count,
  count(distinct country) as country_count,
  max(observed_at) as latest_observed_at
from {table_name}
where {" and ".join(filters)}
group by gpu_model, provider
order by gpu_model, floor_usd_gpu_hr asc
"""


def gpu_listings_sql(
    *,
    table_name: str = "fact_gpu_listings",
    gpu_model: str | None = None,
    provider: str | None = None,
) -> str:
    filters = ["listings.source_availability_status in ('available', 'published_rate')"]
    if gpu_model:
        filters.append(_gpu_selector("listings.gpu_model", gpu_model))
    if provider:
        filters.append(f"listings.provider = {_sql_literal(provider)}")
    return f"""
select
  listings.listing_id,
  listings.provider_id,
  listings.gpu_model,
  listings.gpu_product_id,
  listings.provider,
  listings.source_connector,
  listings.price_usd_gpu_hr,
  listings.price_usd_instance_hr,
  listings.gpu_count,
  listings.available_gpu_count_lower_bound,
  listings.vram_gb,
  listings.country,
  listings.region,
  listings.is_spot,
  listings.is_secure,
  listings.is_available,
  listings.source_availability_status,
  listings.has_raw_evidence,
  listings.source_offer_id,
  listings.source_run_id,
  listings.observed_at
from {table_name} listings
where {" and ".join(filters)}
order by listings.price_usd_gpu_hr asc, listings.price_usd_instance_hr asc
"""


def prime_offer_history_sql(
    *,
    table_name: str = "fact_prime_frontier_offer_reference_history",
    family: str | None = None,
) -> str:
    where = f"where gpu_family_id = {_sql_literal(family.upper())}" if family else ""
    return f"""
select
  gold_observed_at,
  gpu_family_id,
  reference_usd_gpu_hr,
  minimum_executable_reference_usd_gpu_hr,
  best_usd_gpu_hr,
  provider_floor_p25_usd_gpu_hr,
  provider_floor_p75_usd_gpu_hr,
  provider_count,
  configuration_count,
  status,
  gold_run_id
from {table_name}
{where}
order by gold_observed_at, gpu_family_id
"""


def query_gold_gpu_price_index(
    *,
    lake_root: str,
    limit: int | None = None,
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manifest = manifest or read_latest_gold_manifest(lake_root)
    table_ref = manifest["table_refs"].get("fact_gpu_price_index")
    if not table_ref:
        return {"manifest": manifest, "rows": []}

    sql = gpu_price_index_sql()
    rows = DataFusionEngine({"fact_gpu_price_index": table_ref}).query(
        _with_limit(sql, limit)
    )
    return {"manifest": manifest, "rows": rows}


def query_gold_gpu_price_index_history(
    *,
    lake_root: str,
    history_limit: int | None = None,
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Read GPU Price Index history, optionally limited by market run."""
    manifest = manifest or read_latest_gold_manifest(lake_root)
    history_ref = manifest["table_refs"]["fact_gpu_price_index_history"]
    rows = DataFusionEngine({"fact_gpu_price_index_history": str(history_ref)}).query("""
select *
from fact_gpu_price_index_history
order by gold_observed_at, benchmark_family_id
""")
    rows = [
        _current_methodology(row)
        for row in rows
        if is_canonical_market_run_id(row.get("gold_run_id"))
    ]
    selected_runs = list(
        dict.fromkeys(str(row.get("gold_run_id") or "") for row in rows)
    )
    if history_limit is not None:
        selected_runs = selected_runs[-max(1, int(history_limit)) :]
    selected = set(selected_runs)
    rows = [row for row in rows if str(row.get("gold_run_id") or "") in selected]
    return {
        "manifest": manifest,
        "history_manifest_count": len(selected_runs),
        "rows": rows,
    }


def query_gold_gpu_availability(
    *,
    lake_root: str,
    gpu_model: str | None = None,
    measurement_kind: str | None = None,
    history: bool = False,
    limit: int | None = None,
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manifest = manifest or read_latest_gold_manifest(lake_root)
    table_name = "fact_gpu_availability_history" if history else "fact_gpu_availability"
    table_ref = manifest.get("table_refs", {}).get(table_name)
    if not table_ref:
        return {"manifest": manifest, "rows": []}

    sql = gpu_availability_sql(
        table_name=table_name,
        gpu_model=gpu_model,
        measurement_kind=measurement_kind,
    )
    rows = DataFusionEngine({table_name: str(table_ref)}).query(_with_limit(sql, limit))
    return {"manifest": manifest, "rows": rows}


def query_gold_gpu_price_index_constituents(
    *,
    lake_root: str,
    benchmark_family_id: str | None = None,
    limit: int | None = None,
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manifest = manifest or read_latest_gold_manifest(lake_root)
    table_ref = manifest["table_refs"].get("fact_gpu_price_index_constituents")
    if not table_ref:
        return {"manifest": manifest, "rows": []}

    filters = ""
    if benchmark_family_id:
        filters = f"where benchmark_family_id = {_sql_literal(benchmark_family_id)}"
    sql = f"""
select *
from fact_gpu_price_index_constituents
{filters}
order by benchmark_family_id, included desc, constituent_rank asc, price_usd_gpu_hr asc
"""
    rows = DataFusionEngine({"fact_gpu_price_index_constituents": table_ref}).query(
        _with_limit(sql, limit)
    )
    return {"manifest": manifest, "rows": rows}


def query_gold_provider_comparison(
    *,
    lake_root: str,
    gpu_model: str | None = None,
    limit: int | None = None,
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manifest = manifest or read_latest_gold_manifest(lake_root)
    table_ref = manifest["table_refs"]["fact_gpu_listings"]
    sql = provider_comparison_sql(gpu_model=gpu_model)
    rows = DataFusionEngine({"fact_gpu_listings": table_ref}).query(
        _with_limit(sql, limit)
    )
    return {"manifest": manifest, "rows": rows}


def query_gold_listings(
    *,
    lake_root: str,
    gpu_model: str | None = None,
    provider: str | None = None,
    limit: int | None = None,
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manifest = manifest or read_latest_gold_manifest(lake_root)
    table_ref = manifest["table_refs"]["fact_gpu_listings"]
    sql = gpu_listings_sql(
        gpu_model=gpu_model,
        provider=provider,
    )
    rows = DataFusionEngine({"fact_gpu_listings": table_ref}).query(
        _with_limit(sql, limit)
    )
    return {"manifest": manifest, "rows": rows}


def query_gold_prime_frontier_offer_market(
    *,
    lake_root: str,
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Read the maintained Prime frontier references, shelf, and evidence."""
    manifest = manifest or read_latest_gold_manifest(lake_root)
    refs = manifest.get("table_refs", {})
    reference_ref = refs.get("fact_prime_frontier_offer_reference_history")
    if not reference_ref:
        return {
            "manifest": manifest,
            "current": {},
            "last_seen": {},
            "history": [],
            "ladder": [],
            "events": [],
            "event_history": [],
            "offers": [],
        }
    engine = DataFusionEngine(
        {
            table_name: str(ref)
            for table_name in (
                "fact_prime_frontier_offer_reference_history",
                "fact_prime_frontier_offer_ladder",
                "fact_prime_frontier_offer_events",
                "fact_prime_frontier_offer_history",
            )
            if (ref := refs.get(table_name))
        }
    )
    history = engine.query("""
select *
from fact_prime_frontier_offer_reference_history
order by gold_observed_at, gold_run_id, gpu_family_id
""")
    history = [_current_methodology(row) for row in history]
    current_run_id = str(manifest.get("run_id") or "")
    current = {
        str(row.get("gpu_family_id") or ""): row
        for row in history
        if str(row.get("gold_run_id") or "") == current_run_id
    }
    last_seen: dict[str, dict[str, Any]] = {}
    for row in history:
        family_id = str(row.get("gpu_family_id") or "")
        if family_id:
            last_seen[family_id] = row
    ladder: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    event_history: list[dict[str, Any]] = []
    offers: list[dict[str, Any]] = []
    ladder_ref = refs.get("fact_prime_frontier_offer_ladder")
    if ladder_ref:
        ladder = engine.query("""
select *
from fact_prime_frontier_offer_ladder
order by gpu_family_id, price_level_usd_gpu_hr desc
""")
        ladder = [_current_methodology(row) for row in ladder]
    events_ref = refs.get("fact_prime_frontier_offer_events")
    if events_ref:
        event_history = engine.query("""
select *
from fact_prime_frontier_offer_events
where event_type <> 'remained'
order by observed_at, gpu_family_id, event_type, provider
""")
        event_history = [_current_methodology(row) for row in event_history]
    if events_ref and current_run_id:
        events = [
            row
            for row in event_history
            if str(row.get("gold_run_id") or "") == current_run_id
        ]
        remained = engine.query(f"""
select *
from fact_prime_frontier_offer_events
where gold_run_id = {_sql_literal(current_run_id)}
  and event_type = 'remained'
order by gpu_family_id, price_level_usd_gpu_hr desc, provider
""")
        remained = [_current_methodology(row) for row in remained]
        events.extend(remained)
        events.sort(
            key=lambda row: (
                str(row.get("gpu_family_id") or ""),
                -float(row.get("price_level_usd_gpu_hr") or 0),
                str(row.get("event_type") or ""),
                str(row.get("provider") or ""),
            )
        )
    offer_history_ref = refs.get("fact_prime_frontier_offer_history")
    if offer_history_ref and current_run_id:
        offers = engine.query(f"""
select *
from fact_prime_frontier_offer_history
where gold_run_id = {_sql_literal(current_run_id)}
  and source_availability_status = 'available'
  and price_usd_gpu_hr > 0
  and coalesce(is_spot, false) = false
  and coalesce(is_secure, false) = true
order by gpu_family_id, price_usd_gpu_hr asc, provider, gpu_count
""")
    return {
        "manifest": manifest,
        "current": current,
        "last_seen": last_seen,
        "history": history,
        "ladder": ladder,
        "events": events,
        "event_history": event_history,
        "offers": offers,
    }


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _gpu_selector(column: str, value: str) -> str:
    """Match an exact GPU model or all variants in its product family."""
    model = value.strip().upper()
    literal = _sql_literal(model)
    return (
        f"(upper({column}) = {literal} or upper({column}) like concat({literal}, '_%'))"
    )


def _current_methodology(row: dict[str, Any]) -> dict[str, Any]:
    projected = dict(row)
    methodology = projected.pop("methodology_version", None)
    if methodology is not None:
        projected["methodology"] = methodology
    return projected


def _with_limit(sql: str, limit: int | None) -> str:
    if limit is None:
        return sql
    return f"{sql.rstrip()}\nlimit {int(limit)}"
