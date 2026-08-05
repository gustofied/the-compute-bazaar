with source_slots as (
  select count(distinct replicate_index) as source_replicate_slot_count
  from sandbox_workload_latest_replicates
),
summary as (
  select
    series_order,
    series_id,
    series_label,
    color,
    count(*) as result_count,
    max(source_slots.source_replicate_slot_count)
      as source_replicate_slot_count,
    max(source_slots.source_replicate_slot_count) - count(*)
      as incomplete_replicate_count,
    cast(count(*) as double)
      / cast(max(source_slots.source_replicate_slot_count) as double)
      as replicate_completion_ratio,
    count(distinct benchmark_run_id) as run_count,
    min(benchmark_run_id) as benchmark_run_id,
    min(methodology_id) as methodology_id,
    min(source_run_sha) as source_run_sha,
    min(generated_at) as first_generated_at,
    max(generated_at) as latest_generated_at,
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
  from sandbox_workload_latest_replicates
  cross join source_slots
  group by series_order, series_id, series_label, color
)
select
  summary.series_order,
  summary.series_id,
  summary.series_label,
  summary.color,
  summary.result_count,
  summary.source_replicate_slot_count,
  summary.incomplete_replicate_count,
  summary.replicate_completion_ratio,
  summary.run_count,
  summary.benchmark_run_id,
  summary.methodology_id,
  summary.source_run_sha,
  summary.first_generated_at,
  summary.latest_generated_at,
  summary.median_runtime_seconds,
  summary.average_runtime_seconds,
  summary.p25_runtime_seconds,
  summary.p75_runtime_seconds,
  summary.minimum_runtime_seconds,
  summary.maximum_runtime_seconds,
  summary.median_estimated_cost_usd,
  summary.average_estimated_cost_usd,
  summary.p25_estimated_cost_usd,
  summary.p75_estimated_cost_usd,
  summary.minimum_estimated_cost_usd,
  summary.maximum_estimated_cost_usd,
  count(comparison.series_id) = 0 as on_lower_left_frontier
from summary
left join summary comparison
  on comparison.series_id != summary.series_id
 and comparison.median_runtime_seconds <= summary.median_runtime_seconds
 and comparison.median_estimated_cost_usd
   <= summary.median_estimated_cost_usd
 and (
   comparison.median_runtime_seconds < summary.median_runtime_seconds
   or comparison.median_estimated_cost_usd
     < summary.median_estimated_cost_usd
 )
group by
  summary.series_order,
  summary.series_id,
  summary.series_label,
  summary.color,
  summary.result_count,
  summary.source_replicate_slot_count,
  summary.incomplete_replicate_count,
  summary.replicate_completion_ratio,
  summary.run_count,
  summary.benchmark_run_id,
  summary.methodology_id,
  summary.source_run_sha,
  summary.first_generated_at,
  summary.latest_generated_at,
  summary.median_runtime_seconds,
  summary.average_runtime_seconds,
  summary.p25_runtime_seconds,
  summary.p75_runtime_seconds,
  summary.minimum_runtime_seconds,
  summary.maximum_runtime_seconds,
  summary.median_estimated_cost_usd,
  summary.average_estimated_cost_usd,
  summary.p25_estimated_cost_usd,
  summary.p75_estimated_cost_usd,
  summary.minimum_estimated_cost_usd,
  summary.maximum_estimated_cost_usd
order by median_runtime_seconds, median_estimated_cost_usd
