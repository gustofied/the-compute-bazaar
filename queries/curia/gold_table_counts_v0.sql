select 'fact_gpu_listings' as table_name, count(*) as row_count from fact_gpu_listings
union all
select 'fact_price_index_values' as table_name, count(*) as row_count from fact_price_index_values
union all
select 'fact_index_constituents' as table_name, count(*) as row_count from fact_index_constituents
union all
select 'fact_benchmark_values' as table_name, count(*) as row_count from fact_benchmark_values
union all
select 'fact_benchmark_constituents' as table_name, count(*) as row_count from fact_benchmark_constituents
union all
select 'fact_compute_market_state' as table_name, count(*) as row_count from fact_compute_market_state
union all
select 'fact_compute_market_state_history' as table_name, count(*) as row_count from fact_compute_market_state_history
union all
select 'dim_gpu_products' as table_name, count(*) as row_count from dim_gpu_products
union all
select 'dim_providers' as table_name, count(*) as row_count from dim_providers
union all
select 'dim_regions' as table_name, count(*) as row_count from dim_regions
order by table_name
