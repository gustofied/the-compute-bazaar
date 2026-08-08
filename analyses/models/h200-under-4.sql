with hourly as (
  select
    date_trunc('hour', gold_observed_at) as observed_at,
    min(price_usd_gpu_hr) as lowest_price_usd_gpu_hr,
    count(*) filter (where price_usd_gpu_hr < 4) as offers_below_threshold,
    count(distinct provider_id) filter (where price_usd_gpu_hr < 4)
      as providers_below_threshold
  from gold.fact_prime_frontier_offer_history
  where gpu_family_id = 'H200'
  group by date_trunc('hour', gold_observed_at)
)
select
  observed_at,
  lowest_price_usd_gpu_hr,
  offers_below_threshold,
  providers_below_threshold,
  offers_below_threshold > 0 as available_below_threshold
from hourly
order by observed_at
