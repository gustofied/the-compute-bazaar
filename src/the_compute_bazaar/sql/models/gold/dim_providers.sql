with $silver_source_cte,
provider_catalog(provider, provider_kind, observation_kind) as (
  $provider_catalog_values
)
select
  offers.provider as provider_id,
  offers.provider,
  catalog.provider_kind,
  catalog.observation_kind,
  min(observed_at) as first_observed_at,
  max(observed_at) as latest_observed_at,
  $source_run_id as source_run_id,
  $calculated_at as calculated_at
from silver_gpu_offers offers
left join provider_catalog catalog using (provider)
group by offers.provider, catalog.provider_kind, catalog.observation_kind
order by offers.provider
