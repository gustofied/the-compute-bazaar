with recent_observations as (
  select max(gold_observed_at) - interval '7 days' as window_start
  from fact_gpu_price_index_history
)
select
  date_trunc('day', gold_observed_at) as date,
  benchmark_family_id as gpu,
  median(benchmark_usd_gpu_hr) as usd_gpu_hr,
  median(provider_count) as providers,
  median(included_offer_count) as offers
from fact_gpu_price_index_history
cross join recent_observations
where benchmark_family_id in ('H100', 'H200', 'B200', 'B300')
  and gold_observed_at >= recent_observations.window_start
group by 1, 2
order by date, gpu
