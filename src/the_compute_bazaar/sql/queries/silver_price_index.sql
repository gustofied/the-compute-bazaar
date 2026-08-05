with usable_offers as (
  select
    provider,
    gpu_model,
    source_offer_id,
    observed_at,
    price_usd_hr,
    case
      when gpu_count is not null and gpu_count > 0 then price_usd_hr / gpu_count
      else price_usd_hr
    end as unit_price_usd_hr,
    gpu_count,
    country,
    region,
    is_secure,
    is_spot
  from gpu_offers
  where price_usd_hr > 0
    and availability_status in ('available', 'published_rate')
)
select
  gpu_model,
  min(unit_price_usd_hr) as executable_floor_usd_gpu_hr,
  avg(unit_price_usd_hr) as simple_mean_usd_gpu_hr,
  min(price_usd_hr) as cheapest_offer_usd_hr,
  count(*) as offer_count,
  count(distinct provider) as provider_count,
  count(distinct country) as country_count,
  sum(case when is_secure then 1 else 0 end) as secure_offer_count,
  sum(case when is_spot then 1 else 0 end) as spot_offer_count,
  max(observed_at) as latest_observed_at
from usable_offers
group by gpu_model
order by executable_floor_usd_gpu_hr asc, offer_count desc
