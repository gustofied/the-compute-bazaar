select
  offer_reference_symbol,
  reference_scope,
  gpu_family_id,
  gpu_product_family,
  unit,
  price_basis,
  reference_usd_gpu_hr,
  minimum_executable_reference_usd_gpu_hr,
  provider_floor_p25_usd_gpu_hr,
  provider_floor_p75_usd_gpu_hr,
  best_usd_gpu_hr,
  highest_provider_floor_usd_gpu_hr,
  provider_count,
  configuration_count,
  low_price_provider_count,
  status,
  latest_source_observed_at,
  gold_observed_at,
  gold_run_id,
  methodology_version
from fact_prime_frontier_offer_reference_history
order by gold_observed_at desc, gpu_family_id, gold_run_id desc
