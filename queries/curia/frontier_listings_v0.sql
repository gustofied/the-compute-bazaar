select
  gpu_model,
  provider,
  price_usd_gpu_hr,
  price_usd_instance_hr,
  gpu_count,
  vram_gb,
  country,
  region,
  is_spot,
  is_secure,
  availability_status,
  freshness_status,
  has_raw_evidence,
  source_offer_id,
  source_run_id,
  raw_ref,
  source_manifest_ref,
  source_normalized_ref,
  observed_at
from fact_gpu_listings
where availability_status = 'available'
  and (
    gpu_model like 'H100%'
    or gpu_model like 'H200%'
    or gpu_model like 'B200%'
    or gpu_model like 'B300%'
  )
order by gpu_model, price_usd_gpu_hr asc, provider
