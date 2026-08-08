select
  date_trunc('day', gold_observed_at) as observed_at,
  benchmark_family_id as gpu,
  median(benchmark_usd_gpu_hr) as price_usd_gpu_hr,
  median(provider_floor_p25_usd_gpu_hr) as p25_usd_gpu_hr,
  median(provider_floor_p75_usd_gpu_hr) as p75_usd_gpu_hr,
  median(provider_count) as median_provider_count,
  median(included_offer_count) as median_offer_count,
  count(*) as hourly_observations
from fact_gpu_price_index_history
where benchmark_family_id in ('H100', 'H200', 'B200', 'B300')
group by 1, 2
order by observed_at, gpu
