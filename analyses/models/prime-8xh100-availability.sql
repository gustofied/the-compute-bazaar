with observations as (
  select distinct
    gold_observed_at as observed_at
  from gold.fact_prime_frontier_offer_history
),
offer_state as (
  select
    gold_observed_at as observed_at,
    count(*) as visible_offers,
    min(price_usd_gpu_hr) as price_usd_gpu_hr
  from gold.fact_prime_frontier_offer_history
  where gpu_family_id = 'H100'
    and gpu_count = 8
    and provider = 'primecompute'
  group by gold_observed_at
),
timeline as (
  select
    observations.observed_at,
    case when coalesce(offer_state.visible_offers, 0) > 0 then 1 else 0 end
      as available,
    coalesce(offer_state.visible_offers, 0) as visible_offers,
    offer_state.price_usd_gpu_hr
  from observations
  left join offer_state using (observed_at)
),
transitions as (
  select
    *,
    lag(available) over (order by observed_at) as previous_available
  from timeline
)
select
  observed_at,
  available,
  visible_offers,
  price_usd_gpu_hr,
  case when available = 1 and previous_available = 0 then 1 else 0 end as entered,
  case when available = 0 and previous_available = 1 then 1 else 0 end as left_market
from transitions
order by observed_at
