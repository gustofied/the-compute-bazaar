with latest as (
  select max(generated_at) as generated_at
  from sandbox_benchmark_phases
)
select phases.*
from sandbox_benchmark_phases phases
join latest on latest.generated_at = phases.generated_at
order by series_order, replicate_index, task_order
