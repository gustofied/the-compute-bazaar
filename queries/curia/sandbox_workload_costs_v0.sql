select
  series_label,
  median_estimated_cost_usd,
  p25_estimated_cost_usd,
  p75_estimated_cost_usd,
  median_runtime_seconds,
  p25_runtime_seconds,
  p75_runtime_seconds,
  result_count,
  source_replicate_slot_count,
  incomplete_replicate_count,
  replicate_completion_ratio,
  benchmark_run_id,
  methodology_id,
  latest_generated_at
from sandbox_workload_service_summary
order by median_estimated_cost_usd, median_runtime_seconds, series_label
