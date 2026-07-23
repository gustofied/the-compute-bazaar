"""Named DataFusion SQL queries for frontier GPU benchmark products."""

from __future__ import annotations

from typing import Any


BENCHMARK_METHODOLOGY_VERSION = "market_observation_trimmed_mean_v1"
BENCHMARK_VALUES_QUERY_ID = "benchmark_frontier_gpu_families_v1"
BENCHMARK_CONSTITUENTS_QUERY_ID = "benchmark_frontier_gpu_constituents_v1"
BENCHMARK_FAMILIES = [
    {"family_id": "H100", "label": "H100", "gpu_model_prefixes": ["H100_"]},
    {"family_id": "H200", "label": "H200", "gpu_model_prefixes": ["H200_"]},
    {"family_id": "B200", "label": "B200", "gpu_model_prefixes": ["B200_"]},
    {"family_id": "B300", "label": "B300", "gpu_model_prefixes": ["B300_"]},
]


def benchmark_values_v0_sql(context: dict[str, Any]) -> str:
    """Compute frontier GPU benchmark values from gold listings."""
    source_run_id = _sql_literal(str(context["source_run_id"]))
    source_manifest_ref = _sql_literal(str(context["source_manifest_ref"]))
    source_normalized_ref = _sql_literal(str(context["source_normalized_ref"]))
    calculated_at = _sql_literal(str(context["calculated_at"]))
    methodology_version = _sql_literal(BENCHMARK_METHODOLOGY_VERSION)
    query_id = _sql_literal(BENCHMARK_VALUES_QUERY_ID)
    return f"""
with {benchmark_families_cte()},
candidate_offers as (
  select
    families.sort_order,
    families.benchmark_family_id,
    families.benchmark_label,
    families.gpu_model_prefix,
    listings.*
  from fact_gpu_listings listings
  join benchmark_families families
    on listings.gpu_model = rtrim(families.gpu_model_prefix, '_')
    or listings.gpu_model like concat(families.gpu_model_prefix, '%')
  where listings.availability_status in ('available', 'published_rate')
    and listings.price_usd_gpu_hr > 0
),
ranked as (
  select
    *,
    row_number() over(
      partition by benchmark_family_id
      order by price_usd_gpu_hr asc, provider asc, source_offer_id asc
    ) as constituent_rank,
    count(*) over(partition by benchmark_family_id) as family_offer_count
  from candidate_offers
),
scored as (
  select
    *,
    case
      when family_offer_count < 5 then true
      else constituent_rank > case
        when cast(floor(family_offer_count * 0.1) as bigint) < 1 then 1
        else cast(floor(family_offer_count * 0.1) as bigint)
      end
      and constituent_rank <= family_offer_count - case
        when cast(floor(family_offer_count * 0.1) as bigint) < 1 then 1
        else cast(floor(family_offer_count * 0.1) as bigint)
      end
    end as included_in_benchmark
  from ranked
),
aggregated as (
  select
    benchmark_family_id,
    min(price_usd_gpu_hr) as floor_usd_gpu_hr,
    median(price_usd_gpu_hr) as median_usd_gpu_hr,
    avg(price_usd_gpu_hr) as simple_mean_usd_gpu_hr,
    avg(case when included_in_benchmark then price_usd_gpu_hr else null end) as trimmed_mean_usd_gpu_hr,
    percentile_cont(0.25) within group (order by price_usd_gpu_hr) as p25_usd_gpu_hr,
    percentile_cont(0.75) within group (order by price_usd_gpu_hr) as p75_usd_gpu_hr,
    min(price_usd_instance_hr) as cheapest_offer_usd_hr,
    count(*) as offer_count,
    sum(case when included_in_benchmark then 1 else 0 end) as included_offer_count,
    count(distinct provider) as provider_count,
    count(distinct gpu_model) as gpu_model_count,
    count(distinct country) as country_count,
    sum(case when coalesce(is_secure, false) then 1 else 0 end) as secure_offer_count,
    sum(case when coalesce(is_spot, false) then 1 else 0 end) as spot_offer_count,
    max(observed_at) as latest_observed_at
  from scored
  group by benchmark_family_id
)
select
  concat('CBZ-', families.benchmark_family_id, '-OBSERVED:', {source_run_id}) as benchmark_value_id,
  concat('CBZ-', families.benchmark_family_id, '-OBSERVED') as benchmark_symbol,
  families.benchmark_family_id,
  families.benchmark_label,
  make_array(families.gpu_model_prefix) as gpu_model_prefixes,
  {methodology_version} as methodology_version,
  {query_id} as methodology_query_id,
  aggregated.trimmed_mean_usd_gpu_hr as benchmark_usd_gpu_hr,
  aggregated.trimmed_mean_usd_gpu_hr as observed_average_usd_gpu_hr,
  aggregated.floor_usd_gpu_hr,
  aggregated.median_usd_gpu_hr,
  aggregated.simple_mean_usd_gpu_hr,
  aggregated.trimmed_mean_usd_gpu_hr,
  aggregated.p25_usd_gpu_hr,
  aggregated.p75_usd_gpu_hr,
  aggregated.cheapest_offer_usd_hr,
  coalesce(aggregated.offer_count, 0) as offer_count,
  coalesce(aggregated.included_offer_count, 0) as included_offer_count,
  coalesce(aggregated.provider_count, 0) as provider_count,
  coalesce(aggregated.gpu_model_count, 0) as gpu_model_count,
  coalesce(aggregated.country_count, 0) as country_count,
  coalesce(aggregated.secure_offer_count, 0) as secure_offer_count,
  coalesce(aggregated.spot_offer_count, 0) as spot_offer_count,
  aggregated.latest_observed_at,
  case when aggregated.offer_count > 0 then 'observed' else 'not_observed' end as status,
  {source_run_id} as source_run_id,
  {source_manifest_ref} as source_manifest_ref,
  {source_normalized_ref} as source_normalized_ref,
  {calculated_at} as calculated_at
from benchmark_families families
left join aggregated
  on families.benchmark_family_id = aggregated.benchmark_family_id
order by families.sort_order
"""


def benchmark_constituents_v0_sql(context: dict[str, Any]) -> str:
    """Return candidate rows behind frontier GPU benchmarks."""
    source_run_id = _sql_literal(str(context["source_run_id"]))
    source_manifest_ref = _sql_literal(str(context["source_manifest_ref"]))
    source_normalized_ref = _sql_literal(str(context["source_normalized_ref"]))
    calculated_at = _sql_literal(str(context["calculated_at"]))
    methodology_version = _sql_literal(BENCHMARK_METHODOLOGY_VERSION)
    query_id = _sql_literal(BENCHMARK_CONSTITUENTS_QUERY_ID)
    return f"""
with {benchmark_families_cte()},
candidate_offers as (
  select
    families.sort_order,
    families.benchmark_family_id,
    families.benchmark_label,
    families.gpu_model_prefix,
    listings.*
  from fact_gpu_listings listings
  join benchmark_families families
    on listings.gpu_model = rtrim(families.gpu_model_prefix, '_')
    or listings.gpu_model like concat(families.gpu_model_prefix, '%')
  where listings.availability_status in ('available', 'published_rate')
    and listings.price_usd_gpu_hr > 0
),
ranked as (
  select
    *,
    row_number() over(
      partition by benchmark_family_id
      order by price_usd_gpu_hr asc, provider asc, source_offer_id asc
    ) as constituent_rank,
    count(*) over(partition by benchmark_family_id) as family_offer_count
  from candidate_offers
),
scored as (
  select
    *,
    case
      when family_offer_count < 5 then true
      else constituent_rank > case
        when cast(floor(family_offer_count * 0.1) as bigint) < 1 then 1
        else cast(floor(family_offer_count * 0.1) as bigint)
      end
      and constituent_rank <= family_offer_count - case
        when cast(floor(family_offer_count * 0.1) as bigint) < 1 then 1
        else cast(floor(family_offer_count * 0.1) as bigint)
      end
    end as included_in_benchmark
  from ranked
)
select
  concat('CBZ-', benchmark_family_id, '-OBSERVED:', {source_run_id}) as benchmark_value_id,
  concat('CBZ-', benchmark_family_id, '-OBSERVED') as benchmark_symbol,
  benchmark_family_id,
  benchmark_label,
  {methodology_version} as methodology_version,
  {query_id} as methodology_query_id,
  listing_id,
  provider,
  source_offer_id,
  gpu_model,
  gpu_raw_name,
  gpu_count,
  vram_gb,
  price_usd_gpu_hr,
  price_usd_instance_hr,
  country,
  region,
  is_spot,
  is_secure,
  included_in_benchmark as included,
  case when included_in_benchmark then 'available_positive_price' else null end as inclusion_reason,
  case when included_in_benchmark then null else 'trimmed_outlier' end as exclusion_reason,
  constituent_rank,
  constituent_rank = 1 as is_floor_constituent,
  observed_at,
  raw_ref,
  has_raw_evidence,
  {source_run_id} as source_run_id,
  {source_manifest_ref} as source_manifest_ref,
  {source_normalized_ref} as source_normalized_ref,
  {calculated_at} as calculated_at
from scored
order by sort_order, included desc, constituent_rank asc, price_usd_gpu_hr asc
"""


def benchmark_families_cte() -> str:
    return """
benchmark_families(sort_order, benchmark_family_id, benchmark_label, gpu_model_prefix) as (
  values
    (1, 'H100', 'H100', 'H100_'),
    (2, 'H200', 'H200', 'H200_'),
    (3, 'B200', 'B200', 'B200_'),
    (4, 'B300', 'B300', 'B300_')
)
"""


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
