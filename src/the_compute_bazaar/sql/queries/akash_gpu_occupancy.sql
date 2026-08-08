select
  observed_at,
  rented_share * 100.0 as rented_pct,
  available_share * 100.0 as available_pct,
  rented_units,
  available_units,
  total_units
from fact_gpu_availability_history
where lower(provider) = 'akash'
  and measurement_kind = 'rental_occupancy'
  and unit = 'gpu_units'
  and observed_at is not null
order by observed_at
