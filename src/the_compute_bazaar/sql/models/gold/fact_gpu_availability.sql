select *
from $source_table
where resource_market = 'gpu'
order by observed_at, measurement_kind, provider, resource_type, source_connector
