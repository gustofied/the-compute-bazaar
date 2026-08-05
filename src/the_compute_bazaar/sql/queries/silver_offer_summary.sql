select
  gpu_model,
  min(price_usd_hr) as executable_floor,
  avg(price_usd_hr) as simple_mean_price,
  count(*) as offer_count,
  count(distinct provider) as provider_count
from gpu_offers
where price_usd_hr > 0
  and availability_status in ('available', 'published_rate')
group by gpu_model
order by gpu_model
