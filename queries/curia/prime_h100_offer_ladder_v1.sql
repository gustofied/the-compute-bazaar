select
  price_level_usd_gpu_hr,
  configuration_count,
  provider_count,
  single_gpu_configuration_count,
  minimum_offer_usd_gpu_hr,
  maximum_offer_usd_gpu_hr,
  entered_count,
  repriced_count,
  left_availability_count,
  stock_status_changed_count,
  remained_count,
  reference_usd_gpu_hr,
  distance_from_reference_usd_gpu_hr,
  is_reference_level,
  status,
  gold_observed_at,
  gold_run_id,
  methodology_version
from fact_prime_h100_offer_ladder
order by price_level_usd_gpu_hr desc
