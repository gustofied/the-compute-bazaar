with $silver_source_cte
select
  provider as provider_id,
  provider,
  min(observed_at) as first_observed_at,
  max(observed_at) as latest_observed_at,
  $gold_run_id as gold_run_id,
  $calculated_at as calculated_at
from silver_gpu_offers
group by provider
order by provider
