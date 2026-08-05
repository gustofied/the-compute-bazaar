select
  series_label,
  median_estimated_cost_usd,
  p25_estimated_cost_usd,
  p75_estimated_cost_usd,
  result_count,
  benchmark_run_id,
  methodology_id,
  latest_generated_at
from sandbox_workload_service_summary
order by median_estimated_cost_usd, series_label
