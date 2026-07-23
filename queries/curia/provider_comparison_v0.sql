select
  gpu_model,
  provider,
  min(price_usd_gpu_hr) as floor_usd_gpu_hr,
  avg(price_usd_gpu_hr) as simple_mean_usd_gpu_hr,
  min(price_usd_instance_hr) as cheapest_offer_usd_hr,
  count(*) as listing_count,
  count(distinct country) as country_count,
  max(observed_at) as latest_observed_at
from fact_gpu_listings
where availability_status in ('available', 'published_rate')
group by gpu_model, provider
order by gpu_model, floor_usd_gpu_hr asc
