select
  'gpu_benchmark' as market_layer,
  benchmark_label as resource_label,
  cast(null as varchar) as provider_label,
  benchmark_usd_gpu_hr as price_usd_per_hour,
  'USD per GPU hour' as price_unit,
  'one GPU' as requested_shape,
  benchmark_basis as price_basis,
  latest_observed_at as observed_at,
  cast(null as varchar) as source_url,
  methodology_version
from fact_benchmark_values

union all

select
  'vm_offer' as market_layer,
  plan_label as resource_label,
  provider_label,
  price_usd_per_hour,
  'USD per VM hour' as price_unit,
  '4 vCPU / 8 GiB' as requested_shape,
  billing_mode as price_basis,
  checked_at as observed_at,
  source_url,
  methodology_version
from vm_capacity_expanded_current

union all

select
  'managed_sandbox' as market_layer,
  series_label as resource_label,
  series_label as provider_label,
  price_usd_per_hour,
  'USD per sandbox hour' as price_unit,
  '4 processors / 8 GiB' as requested_shape,
  billing_basis_label as price_basis,
  observed_date as observed_at,
  source_url,
  'advertised_fixed_cohort_median_iqr_v2' as methodology_version
from sandbox_current_rates

order by market_layer, price_usd_per_hour, resource_label
