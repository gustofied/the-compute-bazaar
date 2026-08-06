select
  benchmark_family_id,
  benchmark_symbol,
  gpu_model,
  provider,
  price_usd_gpu_hr,
  price_usd_instance_hr,
  gpu_count,
  country,
  region,
  source_availability_status,
  included,
  exclusion_reason,
  constituent_rank,
  provider_rank,
  is_floor_constituent,
  source_offer_id,
  source_run_id,
  raw_ref,
  source_manifest_ref,
  source_normalized_ref,
  observed_at
from fact_gpu_price_index_constituents
order by
  benchmark_family_id,
  included desc,
  constituent_rank,
  price_usd_gpu_hr
