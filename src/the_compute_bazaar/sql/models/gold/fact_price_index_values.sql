with $silver_source_cte,
usable_offers as (
  select
    provider,
    gpu_model,
    source_offer_id,
    observed_at,
    price_usd_hr,
    case
      when gpu_count is not null and gpu_count > 0 then price_usd_hr / gpu_count
      else price_usd_hr
    end as price_usd_gpu_hr,
    country,
    is_spot,
    is_secure
  from silver_gpu_offers
  where price_usd_hr > 0
    and availability_status in ('available', 'published_rate')
)
select
  concat('CBZ-GPU-FLOOR-', gpu_model) as index_symbol,
  gpu_model as gpu_product_id,
  gpu_model,
  'floor_v1' as methodology_version,
  min(price_usd_gpu_hr) as floor_usd_gpu_hr,
  avg(price_usd_gpu_hr) as simple_mean_usd_gpu_hr,
  min(price_usd_hr) as cheapest_offer_usd_hr,
  count(*) as offer_count,
  count(distinct provider) as provider_count,
  count(distinct country) as country_count,
  sum(case when coalesce(is_secure, false) then 1 else 0 end)
    as secure_offer_count,
  sum(case when coalesce(is_spot, false) then 1 else 0 end)
    as spot_offer_count,
  max(observed_at) as latest_observed_at,
  $source_run_id as source_run_id,
  $calculated_at as calculated_at
from usable_offers
group by gpu_model
order by floor_usd_gpu_hr asc, offer_count desc
