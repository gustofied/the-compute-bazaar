with usable_offers as (
  select
    provider,
    gpu_model,
    source_offer_id,
    observed_at,
    price_usd_instance_hr,
    price_usd_gpu_hr,
    gpu_count,
    country,
    region,
    is_secure,
    is_spot
  from gpu_offers
  where price_usd_instance_hr > 0
    and is_available is true
)
select
  gpu_model,
  min(price_usd_gpu_hr) as observed_floor_usd_gpu_hr,
  avg(price_usd_gpu_hr) as simple_mean_usd_gpu_hr,
  min(price_usd_instance_hr) as cheapest_offer_usd_instance_hr,
  count(*) as offer_count,
  count(distinct provider) as provider_count,
  count(distinct country) as country_count,
  sum(case when is_secure then 1 else 0 end) as secure_offer_count,
  sum(case when is_spot then 1 else 0 end) as spot_offer_count,
  max(observed_at) as latest_observed_at
from usable_offers
group by gpu_model
order by observed_floor_usd_gpu_hr asc, offer_count desc
