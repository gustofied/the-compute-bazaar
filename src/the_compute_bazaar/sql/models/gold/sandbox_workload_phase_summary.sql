select
  series_order,
  series_id,
  series_label,
  color,
  task_order,
  task_id,
  task_label,
  count(*) as sample_count,
  median(runtime_seconds) as median_runtime_seconds,
  avg(runtime_seconds) as average_runtime_seconds,
  percentile_cont(0.25) within group (
    order by runtime_seconds
  ) as p25_runtime_seconds,
  percentile_cont(0.75) within group (
    order by runtime_seconds
  ) as p75_runtime_seconds,
  min(runtime_seconds) as minimum_runtime_seconds,
  max(runtime_seconds) as maximum_runtime_seconds
from sandbox_workload_latest_phases
group by
  series_order,
  series_id,
  series_label,
  color,
  task_order,
  task_id,
  task_label
order by series_order, task_order
