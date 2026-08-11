with $silver_source_cte,
products as (
  select *
  from silver_offer_observations
  where gpu_model is not null
    and observation_purpose = 'scheduled'
)
select
  gpu_model as gpu_product_id,
  gpu_model,
  max(vram_gb) as max_vram_gb,
  min(gpu_count) as min_gpu_count,
  max(gpu_count) as max_gpu_count,
  min(observed_at) as first_observed_at,
  max(observed_at) as latest_observed_at,
  $gold_run_id as gold_run_id,
  $calculated_at as calculated_at
from products
group by gpu_model
order by gpu_model
