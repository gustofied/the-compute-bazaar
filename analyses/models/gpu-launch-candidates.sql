with latest_benchmark as (
  select benchmark_family_id, benchmark_usd_gpu_hr, gold_observed_at
  from (
    select
      *,
      row_number() over (
        partition by benchmark_family_id order by gold_observed_at desc
      ) as benchmark_rank
    from gold.fact_gpu_price_index_history
  )
  where benchmark_rank = 1
),
offers as (
  select
    *,
    case
      when gpu_model like 'H100%' then 'H100'
      when gpu_model like 'H200%' then 'H200'
      when gpu_model like 'B200%' then 'B200'
      when gpu_model like 'B300%' then 'B300'
      when gpu_model like 'A100%' then 'A100'
      else gpu_model
    end as gpu_family
  from silver.current_offers
)
select
  offer.observation_id,
  offer.source_offer_id as offer_id,
  offer.provider,
  offer.gpu_family,
  offer.gpu_model,
  offer.gpu_count,
  offer.cloud_type,
  offer.region,
  offer.location_ids_json,
  offer.source_stock_status,
  offer.price_usd_gpu_hr,
  benchmark.benchmark_usd_gpu_hr,
  case
    when benchmark.benchmark_usd_gpu_hr > 0 then
      100 * (
        offer.price_usd_gpu_hr / benchmark.benchmark_usd_gpu_hr - 1
      )
    else null
  end as price_vs_benchmark_pct,
  offer.observed_at,
  benchmark.gold_observed_at as benchmark_observed_at
from offers offer
left join latest_benchmark benchmark
  on benchmark.benchmark_family_id = offer.gpu_family
where offer.is_available
order by offer.price_usd_gpu_hr, offer.provider, offer_id
