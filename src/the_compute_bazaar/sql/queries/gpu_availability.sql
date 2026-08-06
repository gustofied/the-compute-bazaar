select
  observed_at,
  measurement_kind,
  provider,
  source_connector,
  source_role,
  resource_type,
  measurement_scope,
  unit,
  total_units,
  rented_units,
  available_units,
  pending_units,
  rented_share,
  available_share,
  stock_status,
  aggregation_eligible,
  aggregation_exclusion_reason,
  numerator_definition,
  denominator_definition,
  source_url,
  notes
from fact_gpu_availability
order by
  case measurement_kind
    when 'rental_occupancy' then 0
    when 'availability_pressure' then 1
    else 2
  end,
  provider,
  resource_type,
  source_connector
