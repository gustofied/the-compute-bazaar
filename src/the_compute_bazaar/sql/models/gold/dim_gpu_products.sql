with $silver_source_cte,
usable_offers as (
  select *
  from silver_gpu_offers
  where price_usd_hr > 0
)
select
  gpu_model as gpu_product_id,
  gpu_model,
  max(vram_gb) as max_vram_gb,
  min(gpu_count) as min_gpu_count,
  max(gpu_count) as max_gpu_count,
  count(*) as listing_count,
  count(distinct provider) as provider_count,
  min(price_usd_hr / case when gpu_count > 0 then gpu_count else 1 end)
    as floor_usd_gpu_hr,
  max(observed_at) as latest_observed_at,
  $source_run_id as source_run_id,
  $calculated_at as calculated_at
from usable_offers
group by gpu_model
order by floor_usd_gpu_hr asc, listing_count desc
