with eligible_offers as (
  select
    *,
    count(*) over (partition by benchmark_family_id) as family_offer_count
  from fact_gpu_price_index_constituents
  where eligible_for_benchmark
),
row_scored as (
  select
    *,
    case
      when family_offer_count < 5 then true
      else constituent_rank > greatest(
        cast(floor(family_offer_count * 0.1) as bigint),
        1
      )
      and constituent_rank <= family_offer_count - greatest(
        cast(floor(family_offer_count * 0.1) as bigint),
        1
      )
    end as included_in_trimmed_mean
  from eligible_offers
),
offer_aggregated as (
  select
    benchmark_family_id,
    min(sort_order) as sort_order,
    max(benchmark_label) as benchmark_label,
    min(price_usd_gpu_hr) as floor_usd_gpu_hr,
    median(price_usd_gpu_hr) as median_usd_gpu_hr,
    avg(price_usd_gpu_hr) as simple_mean_usd_gpu_hr,
    avg(
      case when included_in_trimmed_mean then price_usd_gpu_hr else null end
    ) as trimmed_mean_usd_gpu_hr,
    percentile_cont(0.25) within group (
      order by price_usd_gpu_hr
    ) as p25_usd_gpu_hr,
    percentile_cont(0.75) within group (
      order by price_usd_gpu_hr
    ) as p75_usd_gpu_hr,
    min(price_usd_instance_hr) as cheapest_offer_usd_instance_hr,
    count(*) as offer_count,
    count(distinct provider) as provider_count,
    count(distinct gpu_model) as gpu_model_count,
    count(distinct country) as country_count,
    sum(case when coalesce(is_secure, false) then 1 else 0 end)
      as secure_offer_count,
    sum(case when coalesce(is_spot, false) then 1 else 0 end)
      as spot_offer_count,
    max(observed_at) as latest_observed_at,
    max(source_run_id) as source_run_id,
    max(source_manifest_ref) as source_manifest_ref,
    max(source_normalized_ref) as source_normalized_ref
  from row_scored
  group by benchmark_family_id
),
provider_aggregated as (
  select
    benchmark_family_id,
    median(price_usd_gpu_hr) as provider_floor_median_usd_gpu_hr,
    avg(price_usd_gpu_hr) as provider_floor_mean_usd_gpu_hr,
    percentile_cont(0.25) within group (
      order by price_usd_gpu_hr
    ) as provider_floor_p25_usd_gpu_hr,
    percentile_cont(0.75) within group (
      order by price_usd_gpu_hr
    ) as provider_floor_p75_usd_gpu_hr,
    count(*) as provider_floor_count
  from fact_gpu_price_index_constituents
  where included
  group by benchmark_family_id
)
select
  concat(
    'CBZ-', offers.benchmark_family_id, '-OBSERVED:', offers.source_run_id
  ) as benchmark_value_id,
  concat('CBZ-', offers.benchmark_family_id, '-OBSERVED') as benchmark_symbol,
  offers.benchmark_family_id,
  offers.benchmark_label,
  ${methodology_version} as methodology_version,
  ${methodology_query_id} as methodology_query_id,
  'observed_advertised_hourly' as benchmark_basis,
  providers.provider_floor_median_usd_gpu_hr as benchmark_usd_gpu_hr,
  providers.provider_floor_median_usd_gpu_hr as observed_average_usd_gpu_hr,
  providers.provider_floor_median_usd_gpu_hr,
  providers.provider_floor_mean_usd_gpu_hr,
  providers.provider_floor_p25_usd_gpu_hr,
  providers.provider_floor_p75_usd_gpu_hr,
  offers.floor_usd_gpu_hr,
  offers.median_usd_gpu_hr,
  offers.simple_mean_usd_gpu_hr,
  offers.trimmed_mean_usd_gpu_hr,
  offers.p25_usd_gpu_hr,
  offers.p75_usd_gpu_hr,
  offers.cheapest_offer_usd_instance_hr,
  offers.offer_count,
  providers.provider_floor_count as included_offer_count,
  offers.provider_count,
  offers.gpu_model_count,
  offers.country_count,
  offers.secure_offer_count,
  offers.spot_offer_count,
  offers.latest_observed_at,
  'observed' as status,
  offers.source_run_id,
  offers.source_manifest_ref,
  offers.source_normalized_ref,
  ${calculated_at} as calculated_at
from offer_aggregated offers
join provider_aggregated providers
  on offers.benchmark_family_id = providers.benchmark_family_id
order by offers.sort_order
