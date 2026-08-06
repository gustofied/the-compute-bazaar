with $silver_source_cte$state_cte,
listing_depth as (
  select
    concat(
      'listing-depth:',
      provider,
      ':',
      coalesce(source_connector, provider),
      ':',
      gpu_model,
      ':',
      $calculated_at
    ) as observation_id,
    max(observed_at) as observed_at,
    'gpu' as resource_market,
    gpu_model as resource_type,
    provider,
    coalesce(source_connector, provider) as source_connector,
    case
      when coalesce(source_connector, provider) <> provider then 'aggregator'
      else 'direct'
    end as source_role,
    'listed_offer_depth' as measurement_kind,
    'normalized_current_offers' as measurement_scope,
    'offers' as unit,
    cast(count(*) as double) as total_units,
    cast(null as double) as rented_units,
    cast(
      sum(
        case
          when is_available is true then 1
          else 0
        end
      ) as double
    ) as available_units,
    cast(null as double) as pending_units,
    cast(null as double) as rented_share,
    cast(
      sum(
        case
          when is_available is true then 1
          else 0
        end
      ) as double
    ) / cast(count(*) as double) as available_share,
    cast(null as varchar) as stock_status,
    'normalized_offer_count' as count_precision,
    'Normalized listings whose source explicitly asserts availability.' as numerator_definition,
    'All normalized current listings from the same provider connector and GPU product.'
      as denominator_definition,
    true as aggregation_eligible,
    cast(null as varchar) as aggregation_exclusion_reason,
    cast(null as varchar) as source_url,
    min(raw_ref) as raw_ref,
    $market_state_methodology_version as methodology_version,
    'Offer depth is a listing-surface measure, not physical fleet capacity or rented share.'
      as notes,
    min(source_run_id) as source_run_id,
    min(source_manifest_ref) as source_manifest_ref,
    min(source_normalized_ref) as source_normalized_ref,
    cast(null as varchar) as source_market_state_ref
  from silver_gpu_offers
  group by provider, coalesce(source_connector, provider), gpu_model
),
all_state as (
  select * from listing_depth
  $state_union
),
direct_keys as (
  select distinct provider, resource_type, measurement_kind
  from all_state
  where source_role = 'direct'
),
ranked_state as (
  select
    state.*,
    direct_keys.provider is not null as matching_direct_source
  from all_state state
  left join direct_keys
    on state.provider = direct_keys.provider
   and state.resource_type = direct_keys.resource_type
   and state.measurement_kind = direct_keys.measurement_kind
)
select
  observation_id,
  observed_at,
  resource_market,
  resource_type,
  provider,
  source_connector,
  source_role,
  measurement_kind,
  measurement_scope,
  unit,
  total_units,
  rented_units,
  available_units,
  pending_units,
  rented_share,
  available_share,
  stock_status,
  count_precision,
  numerator_definition,
  denominator_definition,
  case
    when source_role = 'aggregator' and matching_direct_source then false
    else aggregation_eligible
  end as aggregation_eligible,
  case
    when source_role = 'aggregator' and matching_direct_source
      then 'matching_direct_provider_source'
    else aggregation_exclusion_reason
  end as aggregation_exclusion_reason,
  source_url,
  raw_ref,
  $market_state_methodology_version as methodology_version,
  notes,
  source_run_id,
  source_manifest_ref,
  source_normalized_ref,
  source_market_state_ref,
  $calculated_at as calculated_at,
  $gold_run_id as gold_run_id,
  $calculated_at as gold_observed_at,
  $gold_observed_date as gold_observed_date
from ranked_state
order by measurement_kind, provider, resource_type, source_connector
