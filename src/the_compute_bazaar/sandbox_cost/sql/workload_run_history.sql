select
  benchmark_run_id,
  min(generated_at) as generated_at,
  min(observed_date) as observed_date,
  min(benchmark_source_url) as benchmark_source_url,
  min(methodology_id) as methodology_id,
  min(source_run_sha) as source_run_sha,
  min(task_signature) as task_signature,
  min(workload_app_version) as workload_app_version,
  min(runtime_basis) as runtime_basis,
  min(cost_basis) as cost_basis,
  min(price_scope) as price_scope,
  min(vcpus) as vcpus,
  min(memory_gib) as memory_gib,
  min(disk_gb) as disk_gb,
  min(job_parts) as job_parts,
  count(distinct series_id) as service_count,
  count(distinct series_id) = ${expected_service_count} as service_set_complete,
  median(runtime_seconds) as median_runtime_seconds,
  avg(runtime_seconds) as average_runtime_seconds,
  percentile_cont(0.25) within group (
    order by runtime_seconds
  ) as p25_runtime_seconds,
  percentile_cont(0.75) within group (
    order by runtime_seconds
  ) as p75_runtime_seconds,
  min(runtime_seconds) as minimum_runtime_seconds,
  max(runtime_seconds) as maximum_runtime_seconds,
  median(estimated_cost_usd) as median_estimated_cost_usd,
  avg(estimated_cost_usd) as average_estimated_cost_usd,
  percentile_cont(0.25) within group (
    order by estimated_cost_usd
  ) as p25_estimated_cost_usd,
  percentile_cont(0.75) within group (
    order by estimated_cost_usd
  ) as p75_estimated_cost_usd,
  min(estimated_cost_usd) as minimum_estimated_cost_usd,
  max(estimated_cost_usd) as maximum_estimated_cost_usd
from sandbox_benchmark_batches
group by benchmark_run_id
order by generated_at, benchmark_run_id
