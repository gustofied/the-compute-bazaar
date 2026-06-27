select
  index_symbol,
  gpu_model,
  provider,
  price_usd_gpu_hr,
  included,
  exclusion_reason,
  source_offer_id,
  source_run_id,
  raw_ref,
  source_manifest_ref,
  source_normalized_ref,
  observed_at
from fact_index_constituents
where not included
order by gpu_model, exclusion_reason, price_usd_gpu_hr asc
