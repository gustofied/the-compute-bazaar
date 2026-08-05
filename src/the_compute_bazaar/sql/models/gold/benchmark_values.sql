with benchmark_families(
  sort_order,
  benchmark_family_id,
  benchmark_label,
  gpu_model_prefix
) as (
  values
    (1, 'H100', 'H100', 'H100_'),
    (2, 'H200', 'H200', 'H200_'),
    (3, 'B200', 'B200', 'B200_'),
    (4, 'B300', 'B300', 'B300_')
),
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
  where listings.availability_status in (
    'available',
    'published_rate',
    'published_rate_request'
  )
    and listings.price_usd_gpu_hr > 0
),
ranked as (
  select
    *,
    row_number() over (
      partition by benchmark_family_id
      order by price_usd_gpu_hr, provider, source_offer_id
    ) as constituent_rank,
    row_number() over (
      partition by benchmark_family_id, provider
      order by price_usd_gpu_hr, source_offer_id
    ) as provider_rank,
    count(*) over (partition by benchmark_family_id) as family_offer_count
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
    avg(
      case when included_in_trimmed_mean then price_usd_gpu_hr else null end
    ) as trimmed_mean_usd_gpu_hr,
    percentile_cont(0.25) within group (
      order by price_usd_gpu_hr
    ) as p25_usd_gpu_hr,
    percentile_cont(0.75) within group (
      order by price_usd_gpu_hr
    ) as p75_usd_gpu_hr,
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
    percentile_cont(0.25) within group (
      order by price_usd_gpu_hr
    ) as provider_floor_p25_usd_gpu_hr,
    percentile_cont(0.75) within group (
      order by price_usd_gpu_hr
    ) as provider_floor_p75_usd_gpu_hr,
    count(*) as provider_floor_count
  from provider_floors
  group by benchmark_family_id
)
select
  concat(
    'CBZ-',
    families.benchmark_family_id,
    '-OBSERVED:',
    ${source_run_id}
  ) as benchmark_value_id,
  concat(
    'CBZ-',
    families.benchmark_family_id,
    '-OBSERVED'
  ) as benchmark_symbol,
  families.benchmark_family_id,
  families.benchmark_label,
  make_array(families.gpu_model_prefix) as gpu_model_prefixes,
  ${methodology_version} as methodology_version,
  ${methodology_query_id} as methodology_query_id,
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
  case
    when offer_aggregated.offer_count > 0 then 'observed'
    else 'not_observed'
  end as status,
  ${source_run_id} as source_run_id,
  ${source_manifest_ref} as source_manifest_ref,
  ${source_normalized_ref} as source_normalized_ref,
  ${calculated_at} as calculated_at
from benchmark_families families
left join offer_aggregated
  on families.benchmark_family_id = offer_aggregated.benchmark_family_id
left join provider_aggregated
  on families.benchmark_family_id = provider_aggregated.benchmark_family_id
order by families.sort_order
