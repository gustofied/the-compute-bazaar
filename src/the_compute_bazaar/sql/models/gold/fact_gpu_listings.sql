with $silver_source_cte,
source_catalog(source_connector, source_kind, observation_kind) as (
  $source_catalog_values
)
select
  concat(source_connector, ':', provider, ':', source_offer_id) as listing_id,
  provider as provider_id,
  provider,
  catalog.source_kind,
  catalog.observation_kind,
  source_offer_id,
  gpu_model as gpu_product_id,
  gpu_model,
  gpu_raw_name,
  source_connector,
  gpu_count,
  available_gpu_count_lower_bound,
  vram_gb,
  price_usd_instance_hr,
  price_usd_gpu_hr,
  currency,
  country,
  region,
  case
    when country is null and region is null then 'unknown'
    else concat(coalesce(country, 'unknown'), ':', coalesce(region, 'unknown'))
  end as region_id,
  is_spot,
  is_secure,
  source_availability_status,
  is_available,
  gpu_socket,
  source_stock_status,
  price_is_variable,
  minimum_executable_price_usd_instance_hr,
  required_resource_price_usd_instance_hr,
  price_basis,
  observed_at,
  raw_ref,
  raw_ref is not null as has_raw_evidence,
  source_run_id,
  source_manifest_ref,
  source_normalized_ref,
  $gold_run_id as gold_run_id,
  $calculated_at as calculated_at
from silver_gpu_offers
left join source_catalog catalog using (source_connector)
where price_usd_instance_hr > 0
