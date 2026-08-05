with $silver_source_cte
select
  case
    when country is null and region is null then 'unknown'
    else concat(coalesce(country, 'unknown'), ':', coalesce(region, 'unknown'))
  end as region_id,
  country,
  region,
  count(*) as listing_count,
  count(distinct provider) as provider_count,
  count(distinct gpu_model) as gpu_product_count,
  min(price_usd_hr / case when gpu_count > 0 then gpu_count else 1 end)
    as floor_usd_gpu_hr,
  max(observed_at) as latest_observed_at,
  $source_run_id as source_run_id,
  $calculated_at as calculated_at
from silver_gpu_offers
where price_usd_hr > 0
group by country, region
order by listing_count desc, region_id
