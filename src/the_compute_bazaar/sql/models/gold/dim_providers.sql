with $silver_source_cte
select
  provider as provider_id,
  provider,
  count(*) as listing_count,
  count(distinct source_connector) as source_connector_count,
  count(distinct gpu_model) as gpu_product_count,
  count(distinct country) as country_count,
  min(price_usd_hr / case when gpu_count > 0 then gpu_count else 1 end)
    as floor_usd_gpu_hr,
  max(observed_at) as latest_observed_at,
  $source_run_id as source_run_id,
  $calculated_at as calculated_at
from silver_gpu_offers
where price_usd_hr > 0
group by provider
order by provider
