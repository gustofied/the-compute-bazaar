with eligible as (
  select
    *,
    row_number() over(
      partition by gold_run_id, gpu_family_id, provider
      order by price_usd_gpu_hr asc, gpu_count asc, listing_id asc
    ) as provider_rank
  from fact_prime_frontier_offer_history
  where source_connector = 'prime_intellect'
    and availability_status = 'available'
    and price_usd_gpu_hr > 0
    and coalesce(is_spot, false) = false
    and coalesce(is_secure, false) = true
),
provider_floors as (
  select *
  from eligible
  where provider_rank = 1
),
reference_base as (
  select
    gold_run_id,
    gpu_family_id,
    max(gpu_product_id) as gpu_product_family,
    max(gold_observed_at) as gold_observed_at,
    max(gold_observed_date) as gold_observed_date,
    median(price_usd_gpu_hr) as reference_usd_gpu_hr,
    avg(price_usd_gpu_hr) as provider_floor_mean_usd_gpu_hr,
    percentile_cont(0.25) within group (order by price_usd_gpu_hr)
      as provider_floor_p25_usd_gpu_hr,
    percentile_cont(0.75) within group (order by price_usd_gpu_hr)
      as provider_floor_p75_usd_gpu_hr,
    min(price_usd_gpu_hr) as best_usd_gpu_hr,
    max(price_usd_gpu_hr) as highest_provider_floor_usd_gpu_hr,
    count(*) as provider_count,
    count(distinct country) as country_count,
    sum(case when coalesce(price_is_variable, false) then 1 else 0 end)
      as variable_price_provider_count,
    case
      when count(minimum_executable_price_usd_hr) = count(*)
      then median(minimum_executable_price_usd_hr / gpu_count)
      else cast(null as double)
    end as minimum_executable_reference_usd_gpu_hr,
    max(observed_at) as latest_source_observed_at
  from provider_floors
  group by gold_run_id, gpu_family_id
),
configuration_counts as (
  select
    gold_run_id,
    gpu_family_id,
    count(*) as configuration_count,
    sum(case when gpu_count = 1 then 1 else 0 end)
      as single_gpu_configuration_count,
    count(distinct gpu_socket) as socket_count
  from eligible
  group by gold_run_id, gpu_family_id
),
low_price_breadth as (
  select
    floors.gold_run_id,
    floors.gpu_family_id,
    count(*) as low_price_provider_count
  from provider_floors floors
  join reference_base reference
    on floors.gold_run_id = reference.gold_run_id
   and floors.gpu_family_id = reference.gpu_family_id
  where floors.price_usd_gpu_hr <= reference.reference_usd_gpu_hr * 1.10
  group by floors.gold_run_id, floors.gpu_family_id
)
select
  concat(
    'PRIME-', reference.gpu_family_id, '-OFFER-REFERENCE:',
    reference.gold_run_id
  ) as offer_reference_id,
  concat('PRIME-', reference.gpu_family_id, '-OFFER-REFERENCE')
    as offer_reference_symbol,
  $reference_scope as reference_scope,
  reference.gpu_family_id,
  reference.gpu_product_family,
  'USD_GPU_HOUR' as unit,
  'provider_reported_gpu_base_rate' as price_basis,
  reference.reference_usd_gpu_hr,
  reference.minimum_executable_reference_usd_gpu_hr,
  reference.provider_floor_mean_usd_gpu_hr,
  reference.provider_floor_p25_usd_gpu_hr,
  reference.provider_floor_p75_usd_gpu_hr,
  reference.best_usd_gpu_hr,
  reference.highest_provider_floor_usd_gpu_hr,
  reference.provider_count,
  configurations.configuration_count,
  configurations.single_gpu_configuration_count,
  configurations.socket_count,
  reference.country_count,
  reference.variable_price_provider_count,
  breadth.low_price_provider_count,
  case when reference.provider_count >= 3 then 'observed' else 'indicative' end
    as status,
  reference.latest_source_observed_at,
  reference.gold_run_id,
  reference.gold_observed_at,
  reference.gold_observed_date,
  $methodology_version as methodology_version
from reference_base reference
join configuration_counts configurations
  on reference.gold_run_id = configurations.gold_run_id
 and reference.gpu_family_id = configurations.gpu_family_id
join low_price_breadth breadth
  on reference.gold_run_id = breadth.gold_run_id
 and reference.gpu_family_id = breadth.gpu_family_id
order by
  reference.gold_observed_at,
  reference.gold_run_id,
  reference.gpu_family_id
