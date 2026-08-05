with latest as (
  select max(generated_at) as generated_at
  from sandbox_benchmark_replicates
)
select replicates.*
from sandbox_benchmark_replicates replicates
join latest on latest.generated_at = replicates.generated_at
order by series_order, replicate_index
