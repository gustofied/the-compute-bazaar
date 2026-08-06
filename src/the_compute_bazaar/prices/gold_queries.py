"""Read Gold market tables through DataFusion."""

from __future__ import annotations

from typing import Any

from .datafusion import DataFusionEngine
from .gold_manifest import list_gold_manifests, read_latest_gold_manifest
from .gold_models import BENCHMARK_METHODOLOGY_VERSION


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

    sql = """
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
  methodology_version
from fact_gpu_price_index
order by benchmark_family_id
"""
    rows = DataFusionEngine({"fact_gpu_price_index": table_ref}).query(
        _with_limit(sql, limit)
    )
    return {"manifest": manifest, "rows": rows}


def query_gold_gpu_price_index_history(
    *,
    lake_root: str,
    history_limit: int = 24,
    canonical_market_runs_only: bool = False,
) -> dict[str, Any]:
    """Read GPU Price Index values stored with retained Gold snapshots."""
    manifests = list_gold_manifests(
        lake_root,
        limit=history_limit,
        canonical_market_runs_only=canonical_market_runs_only,
    )
    rows: list[dict[str, Any]] = []
    included_manifest_count = 0

    for manifest in reversed(manifests):
        table_ref = manifest.get("table_refs", {}).get("fact_gpu_price_index")
        if not table_ref:
            continue
        try:
            benchmark_rows = DataFusionEngine(
                {"fact_gpu_price_index": str(table_ref)}
            ).query("""
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
  methodology_version
from fact_gpu_price_index
order by benchmark_family_id
""")
        except Exception as exc:
            raise RuntimeError(
                "Cannot read benchmark history table for Gold run "
                f"{manifest.get('run_id') or '<unknown>'}"
            ) from exc

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
    table_name = (
        "fact_gpu_availability_history" if history else "fact_gpu_availability"
    )
    table_ref = manifest.get("table_refs", {}).get(table_name)
    if not table_ref:
        return {"manifest": manifest, "rows": []}

    filters: list[str] = []
    if gpu_model:
        model = gpu_model.upper()
        filters.append(
            "(upper(resource_type) = "
            f"{_sql_literal(model)} or upper(resource_type) like "
            f"concat({_sql_literal(model)}, '_%'))"
        )
    if measurement_kind:
        filters.append(
            f"measurement_kind = {_sql_literal(measurement_kind)}"
        )
    where = f"where {' and '.join(filters)}" if filters else ""
    sql = f"""
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
  methodology_version
from {table_name}
{where}
order by observed_at desc, measurement_kind, provider, resource_type
"""
    rows = DataFusionEngine({table_name: str(table_ref)}).query(
        _with_limit(sql, limit)
    )
    return {"manifest": manifest, "rows": rows}


def query_gold_gpu_price_index_constituents(
    *,
    lake_root: str,
    benchmark_family_id: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    manifest = read_latest_gold_manifest(lake_root)
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
    filters = ["source_availability_status in ('available', 'published_rate')"]
    if gpu_model:
        filters.append(f"gpu_model = {_sql_literal(gpu_model)}")
    where = f"where {' and '.join(filters)}"
    sql = f"""
select
  gpu_model,
  provider,
  min(price_usd_gpu_hr) as floor_usd_gpu_hr,
  avg(price_usd_gpu_hr) as simple_mean_usd_gpu_hr,
  min(price_usd_instance_hr) as cheapest_offer_usd_instance_hr,
  count(*) as listing_count,
  count(distinct country) as country_count,
  max(observed_at) as latest_observed_at
from fact_gpu_listings
{where}
group by gpu_model, provider
order by gpu_model, floor_usd_gpu_hr asc
"""
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
    filters = ["source_availability_status in ('available', 'published_rate')"]
    if gpu_model:
        filters.append(f"gpu_model = {_sql_literal(gpu_model)}")
    if provider:
        filters.append(f"provider = {_sql_literal(provider)}")
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
  available_gpu_count_lower_bound,
  vram_gb,
  country,
  region,
  is_spot,
  is_secure,
  is_available,
  source_availability_status,
  has_raw_evidence,
  source_offer_id,
  source_run_id,
  observed_at
from fact_gpu_listings
{where}
order by price_usd_gpu_hr asc, price_usd_instance_hr asc
"""
    rows = DataFusionEngine({"fact_gpu_listings": table_ref}).query(
        _with_limit(sql, limit)
    )
    return {"manifest": manifest, "rows": rows}


def query_gold_market_state(
    *, lake_root: str, limit: int | None = None
) -> dict[str, Any]:
    manifest = read_latest_gold_manifest(lake_root)
    table_ref = manifest["table_refs"]["fact_compute_market_state"]
    rows = DataFusionEngine({"fact_compute_market_state": table_ref}).query(
        _with_limit(
            """
select *
from fact_compute_market_state
order by
  case measurement_kind
    when 'rental_occupancy' then 0
    when 'availability_pressure' then 1
    else 2
  end,
  provider,
  resource_type,
  source_connector
""",
            limit,
        ),
    )
    return {"manifest": manifest, "rows": rows}


def query_gold_market_state_history(
    *,
    lake_root: str,
) -> dict[str, Any]:
    manifest = read_latest_gold_manifest(lake_root)
    table_ref = manifest.get("table_refs", {}).get("fact_compute_market_state_history")
    if not table_ref:
        table_ref = manifest.get("table_refs", {}).get("fact_compute_market_state")
    if not table_ref:
        return {"manifest": manifest, "history_manifest_count": 0, "rows": []}
    rows = DataFusionEngine(
        {"fact_compute_market_state_history": str(table_ref)}
    ).query("""
select *
from fact_compute_market_state_history
where measurement_kind in ('rental_occupancy', 'availability_pressure')
order by gold_observed_at, measurement_kind, provider, resource_type, source_connector
""")
    run_ids = {
        str(row.get("gold_run_id") or "") for row in rows if row.get("gold_run_id")
    }
    return {
        "manifest": manifest,
        "history_manifest_count": len(run_ids),
        "rows": rows,
    }


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
    events_ref = refs.get("fact_prime_frontier_offer_events")
    if events_ref:
        event_history = engine.query("""
select *
from fact_prime_frontier_offer_events
where event_type <> 'remained'
order by observed_at, gpu_family_id, event_type, provider
""")
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


def _with_limit(sql: str, limit: int | None) -> str:
    if limit is None:
        return sql
    return f"{sql.rstrip()}\nlimit {int(limit)}"
