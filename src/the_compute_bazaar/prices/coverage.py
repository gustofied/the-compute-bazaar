"""Frontier GPU observation coverage measured with DataFusion."""

from __future__ import annotations

from typing import Any

from .datafusion import query_parquet
from .gold import read_latest_gold_manifest


FRONTIER_COVERAGE_TARGET = 50
FRONTIER_FAMILIES = ("H100", "H200", "B200", "B300")


def query_frontier_coverage(
    *,
    lake_root: str,
    target: int = FRONTIER_COVERAGE_TARGET,
    capacity_target: int = FRONTIER_COVERAGE_TARGET,
    observation_target: int = FRONTIER_COVERAGE_TARGET,
) -> dict[str, Any]:
    manifest = read_latest_gold_manifest(lake_root)
    table_ref = str(manifest["table_refs"]["fact_gpu_listings"])
    rows = query_frontier_coverage_ref(
        table_ref=table_ref,
        target=target,
        capacity_target=capacity_target,
        observation_target=observation_target,
    )
    return {
        "manifest": manifest,
        "target_live_offer_count": target,
        "target_live_gpu_capacity": capacity_target,
        "target_current_observation_count": observation_target,
        "rows": rows,
    }


def query_frontier_coverage_ref(
    *,
    table_ref: str,
    target: int = FRONTIER_COVERAGE_TARGET,
    capacity_target: int = FRONTIER_COVERAGE_TARGET,
    observation_target: int = FRONTIER_COVERAGE_TARGET,
) -> list[dict[str, Any]]:
    sql = """
with frontier_families(sort_order, gpu_family, gpu_model_prefix) as (
  values
    (1, 'H100', 'H100_'),
    (2, 'H200', 'H200_'),
    (3, 'B200', 'B200_'),
    (4, 'B300', 'B300_')
),
matched as (
  select
    families.sort_order,
    families.gpu_family,
    listings.provider,
    coalesce(listings.source_connector, listings.provider) as source_connector,
    listings.availability_status,
    listings.gpu_count,
    listings.available_gpu_count
  from frontier_families families
  left join fact_gpu_listings listings
    on listings.gpu_model = rtrim(families.gpu_model_prefix, '_')
    or listings.gpu_model like concat(families.gpu_model_prefix, '%')
),
capacity_by_connector as (
  select
    sort_order,
    gpu_family,
    provider,
    source_connector,
    sum(
      case
        when availability_status in (
          'available',
          'spot_available',
          'available_component_rate'
        )
        then coalesce(available_gpu_count, gpu_count, 0)
        else 0
      end
    ) as connector_capacity
  from matched
  where provider is not null
  group by sort_order, gpu_family, provider, source_connector
),
capacity_by_provider as (
  select
    sort_order,
    gpu_family,
    provider,
    max(connector_capacity) as provider_capacity
  from capacity_by_connector
  group by sort_order, gpu_family, provider
),
capacity_totals as (
  select
    sort_order,
    gpu_family,
    sum(provider_capacity) as live_gpu_capacity_lower_bound
  from capacity_by_provider
  group by sort_order, gpu_family
),
listing_metrics as (
  select
    sort_order,
    gpu_family,
    sum(
      case when availability_status in ('available', 'spot_available') then 1 else 0 end
    ) as live_offer_count,
    count(
      distinct case
        when availability_status in ('available', 'spot_available') then provider
        else null
      end
    ) as live_provider_count,
    count(
      distinct case
        when availability_status in (
          'available',
          'spot_available',
          'available_component_rate'
        )
        then provider
        else null
      end
    ) as live_capacity_provider_count,
    sum(case when availability_status = 'available' then 1 else 0 end) as live_on_demand_offer_count,
    sum(case when availability_status = 'spot_available' then 1 else 0 end) as live_spot_offer_count,
    sum(
      case when availability_status = 'available_component_rate' then 1 else 0 end
    ) as live_component_rate_offer_count,
    sum(case when availability_status = 'spot_price_observed' then 1 else 0 end) as spot_price_observation_count,
    count(
      distinct case when availability_status = 'spot_price_observed' then provider else null end
    ) as spot_provider_count,
    sum(
      case
        when availability_status in ('published_rate', 'published_rate_request', 'published_rate_spot')
        then 1
        else 0
      end
    ) as published_rate_count,
    count(
      distinct case
        when availability_status in ('published_rate', 'published_rate_request', 'published_rate_spot')
        then provider
        else null
      end
    ) as published_rate_provider_count,
    sum(
      case
        when availability_status in (
          'published_rate_future',
          'published_rate_reserved',
          'published_rate_expired'
        )
        then 1
        else 0
      end
    ) as non_current_rate_count,
    sum(
      case
        when availability_status in ('available', 'spot_available')
          or availability_status = 'spot_price_observed'
          or availability_status in ('published_rate', 'published_rate_request', 'published_rate_spot')
        then 1
        else 0
      end
    ) as current_observation_count
  from matched
  group by sort_order, gpu_family
)
select
  metrics.*,
  coalesce(capacity.live_gpu_capacity_lower_bound, 0) as live_gpu_capacity_lower_bound
from listing_metrics metrics
left join capacity_totals capacity
  on metrics.sort_order = capacity.sort_order
  and metrics.gpu_family = capacity.gpu_family
order by metrics.sort_order
"""
    rows = query_parquet(
        parquet_uri=table_ref,
        table_name="fact_gpu_listings",
        sql=sql,
    )
    for row in rows:
        live_count = int(row.get("live_offer_count") or 0)
        row["target_live_offer_count"] = int(target)
        row["shortfall_to_target"] = max(0, int(target) - live_count)
        row["target_met"] = live_count >= int(target)
        capacity_count = int(row.get("live_gpu_capacity_lower_bound") or 0)
        row["target_live_gpu_capacity"] = int(capacity_target)
        row["capacity_shortfall_to_target"] = max(
            0,
            int(capacity_target) - capacity_count,
        )
        row["capacity_target_met"] = capacity_count >= int(capacity_target)
        observation_count = int(row.get("current_observation_count") or 0)
        row["target_current_observation_count"] = int(observation_target)
        row["observation_shortfall_to_target"] = max(
            0,
            int(observation_target) - observation_count,
        )
        row["observation_target_met"] = observation_count >= int(observation_target)
        row.pop("sort_order", None)
    return rows
