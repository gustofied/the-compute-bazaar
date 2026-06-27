select
  benchmark_family_id,
  benchmark_symbol,
  benchmark_label,
  benchmark_usd_gpu_hr,
  floor_usd_gpu_hr,
  median_usd_gpu_hr,
  trimmed_mean_usd_gpu_hr,
  offer_count,
  included_offer_count,
  provider_count,
  latest_observed_at,
  status,
  methodology_version,
  methodology_query_id
from fact_benchmark_values
order by benchmark_family_id
