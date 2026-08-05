with $silver_source_cte,
candidate_offers as (
  select
    concat(provider, ':', source_offer_id) as listing_id,
    provider,
    source_connector,
    source_offer_id,
    gpu_model,
    available_gpu_count,
    price_usd_hr,
    case
      when gpu_count is not null and gpu_count > 0 then price_usd_hr / gpu_count
      else price_usd_hr
    end as price_usd_gpu_hr,
    country,
    region,
    availability_status,
    case
      when price_usd_hr is null or price_usd_hr <= 0 then false
      when availability_status not in ('available', 'published_rate') then false
      else true
    end as included,
    case
      when price_usd_hr is null or price_usd_hr <= 0 then 'non_positive_price'
      when availability_status not in ('available', 'published_rate')
        then 'not_available'
      else null
    end as exclusion_reason,
    observed_at
  from silver_gpu_offers
),
ranked as (
  select
    *,
    case
      when included then row_number() over(
        partition by gpu_model, included
        order by price_usd_gpu_hr asc, price_usd_hr asc
      )
      else null
    end as constituent_rank
  from candidate_offers
)
select
  concat('CBZ-GPU-FLOOR-', gpu_model, ':', $source_run_id) as index_value_id,
  concat('CBZ-GPU-FLOOR-', gpu_model) as index_symbol,
  gpu_model as gpu_product_id,
  gpu_model,
  listing_id,
  provider,
  source_connector,
  source_offer_id,
  price_usd_hr,
  price_usd_gpu_hr,
  available_gpu_count,
  country,
  region,
  availability_status,
  included,
  exclusion_reason,
  observed_at,
  constituent_rank,
  included and constituent_rank = 1 as is_floor_constituent,
  $source_run_id as source_run_id,
  $source_manifest_ref as source_manifest_ref,
  $source_normalized_ref as source_normalized_ref,
  $calculated_at as calculated_at
from ranked
order by gpu_model, included desc, constituent_rank asc, price_usd_gpu_hr asc
