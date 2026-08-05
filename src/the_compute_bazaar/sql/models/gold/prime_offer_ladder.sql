with latest_reference as (
  select *
  from fact_prime_frontier_offer_reference_history
  where gold_run_id = $current_gold_run_id
),
benchmark_current as (
  select
    benchmark_family_id as gpu_family_id,
    benchmark_usd_gpu_hr as market_benchmark_usd_gpu_hr,
    provider_floor_p25_usd_gpu_hr as market_benchmark_p25_usd_gpu_hr,
    provider_floor_p75_usd_gpu_hr as market_benchmark_p75_usd_gpu_hr,
    provider_count as market_benchmark_provider_count
  from fact_benchmark_values
),
reference_with_benchmark as (
  select
    reference.*,
    benchmark.market_benchmark_usd_gpu_hr,
    benchmark.market_benchmark_p25_usd_gpu_hr,
    benchmark.market_benchmark_p75_usd_gpu_hr,
    benchmark.market_benchmark_provider_count,
    coalesce(
      benchmark.market_benchmark_usd_gpu_hr,
      reference.reference_usd_gpu_hr
    ) as center_usd_gpu_hr
  from latest_reference reference
  left join benchmark_current benchmark
    on reference.gpu_family_id = benchmark.gpu_family_id
),
current_offers as (
  select
    history.*,
    round(history.price_usd_gpu_hr / $price_increment) * $price_increment
      as price_level_usd_gpu_hr
  from fact_prime_frontier_offer_history history
  join reference_with_benchmark reference
    on history.gold_run_id = reference.gold_run_id
   and history.gpu_family_id = reference.gpu_family_id
  where history.availability_status = 'available'
    and history.price_usd_gpu_hr > 0
    and coalesce(history.is_spot, false) = false
    and coalesce(history.is_secure, false) = true
),
offer_levels as (
  select
    gpu_family_id,
    price_level_usd_gpu_hr,
    count(*) as configuration_count,
    count(distinct provider) as provider_count,
    sum(case when gpu_count = 1 then 1 else 0 end)
      as single_gpu_configuration_count,
    min(price_usd_gpu_hr) as minimum_offer_usd_gpu_hr,
    max(price_usd_gpu_hr) as maximum_offer_usd_gpu_hr
  from current_offers
  group by gpu_family_id, price_level_usd_gpu_hr
),
latest_events as (
  select events.*
  from fact_prime_frontier_offer_events events
  join reference_with_benchmark reference
    on events.gold_run_id = reference.gold_run_id
   and events.gpu_family_id = reference.gpu_family_id
),
event_levels as (
  select
    gpu_family_id,
    price_level_usd_gpu_hr,
    sum(case when event_type = 'entered' then 1 else 0 end) as entered_count,
    sum(case when event_type in ('repriced_up', 'repriced_down') then 1 else 0 end)
      as repriced_count,
    sum(case when event_type = 'left_availability' then 1 else 0 end)
      as left_availability_count,
    sum(case when event_type = 'stock_status_changed' then 1 else 0 end)
      as stock_status_changed_count,
    sum(case when event_type = 'remained' then 1 else 0 end) as remained_count
  from latest_events
  where price_level_usd_gpu_hr is not null
  group by gpu_family_id, price_level_usd_gpu_hr
),
reference_grid as (
  select
    reference.gpu_family_id,
    round(reference.center_usd_gpu_hr / $price_increment) * $price_increment
      + offsets.offset * $price_increment as price_level_usd_gpu_hr
  from reference_with_benchmark reference
  cross join (
    values (-6), (-5), (-4), (-3), (-2), (-1), (0),
           (1), (2), (3), (4), (5), (6)
  ) as offsets(offset)
),
all_levels as (
  select gpu_family_id, price_level_usd_gpu_hr from reference_grid
  union
  select gpu_family_id, price_level_usd_gpu_hr from offer_levels
  union
  select gpu_family_id, price_level_usd_gpu_hr from event_levels
),
joined as (
  select
    levels.gpu_family_id,
    levels.price_level_usd_gpu_hr,
    coalesce(offers.configuration_count, 0) as configuration_count,
    coalesce(offers.provider_count, 0) as provider_count,
    coalesce(offers.single_gpu_configuration_count, 0)
      as single_gpu_configuration_count,
    offers.minimum_offer_usd_gpu_hr,
    offers.maximum_offer_usd_gpu_hr,
    coalesce(events.entered_count, 0) as entered_count,
    coalesce(events.repriced_count, 0) as repriced_count,
    coalesce(events.left_availability_count, 0) as left_availability_count,
    coalesce(events.stock_status_changed_count, 0)
      as stock_status_changed_count,
    coalesce(events.remained_count, 0) as remained_count,
    reference.reference_usd_gpu_hr,
    reference.market_benchmark_usd_gpu_hr,
    reference.market_benchmark_p25_usd_gpu_hr,
    reference.market_benchmark_p75_usd_gpu_hr,
    reference.market_benchmark_provider_count,
    levels.price_level_usd_gpu_hr - reference.reference_usd_gpu_hr
      as distance_from_prime_reference_usd_gpu_hr,
    levels.price_level_usd_gpu_hr - reference.center_usd_gpu_hr
      as distance_from_market_benchmark_usd_gpu_hr,
    case
      when reference.market_benchmark_usd_gpu_hr > 0
      then levels.price_level_usd_gpu_hr
        / reference.market_benchmark_usd_gpu_hr - 1
      else cast(null as double)
    end as premium_to_market_benchmark_fraction,
    abs(levels.price_level_usd_gpu_hr - reference.reference_usd_gpu_hr)
      <= $half_price_increment as is_prime_reference_level,
    abs(levels.price_level_usd_gpu_hr - reference.center_usd_gpu_hr)
      <= $half_price_increment as is_market_benchmark_level,
    reference.gold_run_id,
    reference.gold_observed_at,
    reference.status,
    reference.methodology_version
  from all_levels levels
  join reference_with_benchmark reference
    on levels.gpu_family_id = reference.gpu_family_id
  left join offer_levels offers
    on levels.gpu_family_id = offers.gpu_family_id
   and levels.price_level_usd_gpu_hr = offers.price_level_usd_gpu_hr
  left join event_levels events
    on levels.gpu_family_id = events.gpu_family_id
   and levels.price_level_usd_gpu_hr = events.price_level_usd_gpu_hr
)
select
  *,
  row_number() over(
    partition by gpu_family_id
    order by price_level_usd_gpu_hr desc
  ) as price_level_rank
from joined
order by gpu_family_id, price_level_usd_gpu_hr desc
