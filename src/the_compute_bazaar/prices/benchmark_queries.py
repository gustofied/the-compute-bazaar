"""Named DataFusion SQL queries for frontier GPU benchmark products."""

from __future__ import annotations

from typing import Any


BENCHMARK_METHODOLOGY_VERSION = "advertised_provider_floor_median_v1"
BENCHMARK_VALUES_QUERY_ID = "benchmark_frontier_gpu_families_v2"
BENCHMARK_CONSTITUENTS_QUERY_ID = "benchmark_frontier_gpu_constituents_v2"
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
  where listings.availability_status in ('available', 'published_rate', 'published_rate_request')
    and listings.price_usd_gpu_hr > 0
),
ranked as (
  select
    *,
    row_number() over(
      partition by benchmark_family_id
      order by price_usd_gpu_hr asc, provider asc, source_offer_id asc
    ) as constituent_rank,
    row_number() over(
      partition by benchmark_family_id, provider
      order by price_usd_gpu_hr asc, source_offer_id asc
    ) as provider_rank,
    count(*) over(partition by benchmark_family_id) as family_offer_count
  from candidate_offers
),
row_scored as (
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
    end as included_in_trimmed_mean
  from ranked
),
provider_floors as (
  select *
  from row_scored
  where provider_rank = 1
),
offer_aggregated as (
  select
    benchmark_family_id,
    min(price_usd_gpu_hr) as floor_usd_gpu_hr,
    median(price_usd_gpu_hr) as median_usd_gpu_hr,
    avg(price_usd_gpu_hr) as simple_mean_usd_gpu_hr,
    avg(case when included_in_trimmed_mean then price_usd_gpu_hr else null end) as trimmed_mean_usd_gpu_hr,
    percentile_cont(0.25) within group (order by price_usd_gpu_hr) as p25_usd_gpu_hr,
    percentile_cont(0.75) within group (order by price_usd_gpu_hr) as p75_usd_gpu_hr,
    min(price_usd_hr) as cheapest_offer_usd_hr,
    count(*) as offer_count,
    count(distinct provider) as provider_count,
    count(distinct gpu_model) as gpu_model_count,
    count(distinct country) as country_count,
    sum(case when coalesce(is_secure, false) then 1 else 0 end) as secure_offer_count,
    sum(case when coalesce(is_spot, false) then 1 else 0 end) as spot_offer_count,
    max(observed_at) as latest_observed_at
  from row_scored
  group by benchmark_family_id
),
provider_aggregated as (
  select
    benchmark_family_id,
    median(price_usd_gpu_hr) as provider_floor_median_usd_gpu_hr,
    avg(price_usd_gpu_hr) as provider_floor_mean_usd_gpu_hr,
    percentile_cont(0.25) within group (order by price_usd_gpu_hr) as provider_floor_p25_usd_gpu_hr,
    percentile_cont(0.75) within group (order by price_usd_gpu_hr) as provider_floor_p75_usd_gpu_hr,
    count(*) as provider_floor_count
  from provider_floors
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
  'advertised_hourly' as benchmark_basis,
  provider_aggregated.provider_floor_median_usd_gpu_hr as benchmark_usd_gpu_hr,
  provider_aggregated.provider_floor_median_usd_gpu_hr as observed_average_usd_gpu_hr,
  provider_aggregated.provider_floor_median_usd_gpu_hr,
  provider_aggregated.provider_floor_mean_usd_gpu_hr,
  provider_aggregated.provider_floor_p25_usd_gpu_hr,
  provider_aggregated.provider_floor_p75_usd_gpu_hr,
  offer_aggregated.floor_usd_gpu_hr,
  offer_aggregated.median_usd_gpu_hr,
  offer_aggregated.simple_mean_usd_gpu_hr,
  offer_aggregated.trimmed_mean_usd_gpu_hr,
  offer_aggregated.p25_usd_gpu_hr,
  offer_aggregated.p75_usd_gpu_hr,
  offer_aggregated.cheapest_offer_usd_hr,
  coalesce(offer_aggregated.offer_count, 0) as offer_count,
  coalesce(provider_aggregated.provider_floor_count, 0) as included_offer_count,
  coalesce(offer_aggregated.provider_count, 0) as provider_count,
  coalesce(offer_aggregated.gpu_model_count, 0) as gpu_model_count,
  coalesce(offer_aggregated.country_count, 0) as country_count,
  coalesce(offer_aggregated.secure_offer_count, 0) as secure_offer_count,
  coalesce(offer_aggregated.spot_offer_count, 0) as spot_offer_count,
  offer_aggregated.latest_observed_at,
  case when offer_aggregated.offer_count > 0 then 'observed' else 'not_observed' end as status,
  {source_run_id} as source_run_id,
  {source_manifest_ref} as source_manifest_ref,
  {source_normalized_ref} as source_normalized_ref,
  {calculated_at} as calculated_at
from benchmark_families families
left join offer_aggregated
  on families.benchmark_family_id = offer_aggregated.benchmark_family_id
left join provider_aggregated
  on families.benchmark_family_id = provider_aggregated.benchmark_family_id
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
frontier_offers as (
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
  where listings.price_usd_gpu_hr > 0
),
eligible_ranked as (
  select
    *,
    row_number() over(
      partition by benchmark_family_id
      order by price_usd_gpu_hr asc, provider asc, source_offer_id asc
    ) as constituent_rank,
    row_number() over(
      partition by benchmark_family_id, provider
      order by price_usd_gpu_hr asc, source_offer_id asc
    ) as provider_rank
  from frontier_offers
  where availability_status in ('available', 'published_rate', 'published_rate_request')
)
select
  concat('CBZ-', frontier.benchmark_family_id, '-OBSERVED:', {source_run_id}) as benchmark_value_id,
  concat('CBZ-', frontier.benchmark_family_id, '-OBSERVED') as benchmark_symbol,
  frontier.benchmark_family_id,
  frontier.benchmark_label,
  {methodology_version} as methodology_version,
  {query_id} as methodology_query_id,
  frontier.listing_id,
  frontier.provider,
  frontier.source_connector,
  frontier.source_offer_id,
  frontier.gpu_model,
  frontier.gpu_raw_name,
  frontier.gpu_count,
  frontier.available_gpu_count,
  frontier.vram_gb,
  frontier.price_usd_gpu_hr,
  frontier.price_usd_instance_hr,
  frontier.country,
  frontier.region,
  frontier.is_spot,
  frontier.is_secure,
  frontier.availability_status,
  coalesce(eligible.provider_rank = 1, false) as included,
  case when eligible.provider_rank = 1 then 'provider_floor' else null end as inclusion_reason,
  case
    when eligible.provider_rank = 1 then null
    when frontier.availability_status in ('spot_available', 'spot_price_observed')
      then 'different_price_basis_spot'
    when frontier.availability_status = 'published_rate_future' then 'future_rate'
    when frontier.availability_status = 'published_rate_reserved' then 'committed_term_rate'
    when frontier.availability_status not in ('available', 'published_rate', 'published_rate_request')
      then 'not_currently_available'
    when eligible.provider_rank > 1 then 'higher_same_provider_offer'
    else 'not_eligible'
  end as exclusion_reason,
  eligible.constituent_rank,
  eligible.provider_rank,
  coalesce(eligible.constituent_rank = 1, false) as is_floor_constituent,
  frontier.observed_at,
  frontier.raw_ref,
  frontier.has_raw_evidence,
  {source_run_id} as source_run_id,
  {source_manifest_ref} as source_manifest_ref,
  {source_normalized_ref} as source_normalized_ref,
  {calculated_at} as calculated_at
from frontier_offers frontier
left join eligible_ranked eligible
  on frontier.listing_id = eligible.listing_id
order by frontier.sort_order, included desc, eligible.constituent_rank asc, frontier.price_usd_gpu_hr asc
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
