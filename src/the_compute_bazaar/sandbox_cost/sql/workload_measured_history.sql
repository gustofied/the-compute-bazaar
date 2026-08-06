select
  observed_date,
  series_order,
  series_id,
  series_label,
  min(color) as color,
  min(generated_at) as first_generated_at,
  max(generated_at) as latest_generated_at,
  count(*) as observation_count,
  count(distinct benchmark_run_id) as source_run_count,
  count(distinct methodology_id) as methodology_count,
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
group by
  observed_date,
  series_order,
  series_id,
  series_label
order by observed_date, series_order
