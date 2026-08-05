with $silver_source_cte
select
  concat(provider, ':', source_offer_id) as listing_id,
  provider as provider_id,
  provider,
  source_offer_id,
  gpu_model as gpu_product_id,
  gpu_model,
  gpu_raw_name,
  source_connector,
  gpu_count,
  available_gpu_count,
  vram_gb,
  price_usd_hr,
  price_usd_hr as price_usd_instance_hr,
  case
    when gpu_count is not null and gpu_count > 0 then price_usd_hr / gpu_count
    else price_usd_hr
  end as price_usd_gpu_hr,
  currency,
  country,
  region,
  case
    when country is null and region is null then 'unknown'
    else concat(coalesce(country, 'unknown'), ':', coalesce(region, 'unknown'))
  end as region_id,
  is_spot,
  is_secure,
  availability_status,
  gpu_socket,
  stock_status,
  price_is_variable,
  minimum_executable_price_usd_hr,
  required_resource_price_usd_hr,
  price_basis,
  'fresh' as freshness_status,
  observed_at,
  raw_ref,
  raw_ref is not null as has_raw_evidence,
  $source_run_id as source_run_id,
  $source_manifest_ref as source_manifest_ref,
  $source_normalized_ref as source_normalized_ref,
  $calculated_at as calculated_at
from silver_gpu_offers
where price_usd_hr > 0
