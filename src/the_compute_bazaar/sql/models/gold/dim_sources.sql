with $silver_source_cte,
source_catalog(source_connector, source_kind, observation_kind) as (
  $source_catalog_values
)
select
  offers.source_connector as source_id,
  offers.source_connector,
  catalog.source_kind,
  catalog.observation_kind,
  min(offers.observed_at) as first_observed_at,
  max(offers.observed_at) as latest_observed_at,
  $gold_run_id as gold_run_id,
  $calculated_at as calculated_at
from silver_offer_observations offers
left join source_catalog catalog using (source_connector)
where offers.observation_purpose = 'scheduled'
group by
  offers.source_connector,
  catalog.source_kind,
  catalog.observation_kind
order by offers.source_connector
