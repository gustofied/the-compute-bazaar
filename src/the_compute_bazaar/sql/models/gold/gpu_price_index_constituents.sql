with benchmark_families(
  sort_order,
  benchmark_family_id,
  benchmark_label,
  gpu_model_prefix
) as (
  values
    (1, 'H100', 'H100', 'H100_'),
    (2, 'H200', 'H200', 'H200_'),
    (3, 'B200', 'B200', 'B200_'),
    (4, 'B300', 'B300', 'B300_')
),
frontier_offers as (
  select
    families.sort_order,
    families.benchmark_family_id,
    families.benchmark_label,
    families.gpu_model_prefix,
    listings.*
  from fact_gpu_listings listings
  join benchmark_families families
    on listings.gpu_model = rtrim(families.gpu_model_prefix, '_')
    or listings.gpu_model like concat(families.gpu_model_prefix, '%')
  where listings.price_usd_gpu_hr > 0
),
eligible_ranked as (
  select
    *,
    row_number() over (
      partition by benchmark_family_id
      order by price_usd_gpu_hr, provider, source_offer_id
    ) as constituent_rank,
    row_number() over (
      partition by benchmark_family_id, provider
      order by price_usd_gpu_hr, source_offer_id
    ) as provider_rank
  from frontier_offers
  where source_availability_status in (
    'available',
    'published_rate'
  )
    and observation_kind in (
      'live_offer',
      'published_rate',
      'mixed_advertised_price'
    )
    and coalesce(is_spot, false) = false
)
select
  frontier.sort_order,
  concat(
    'CBZ-',
    frontier.benchmark_family_id,
    '-OBSERVED:',
    ${gold_run_id}
  ) as benchmark_value_id,
  concat(
    'CBZ-',
    frontier.benchmark_family_id,
    '-OBSERVED'
  ) as benchmark_symbol,
  frontier.benchmark_family_id,
  frontier.benchmark_label,
  ${methodology_version} as methodology_version,
  ${methodology_query_id} as methodology_query_id,
  frontier.listing_id,
  frontier.provider,
  frontier.source_kind,
  frontier.observation_kind,
  frontier.source_connector,
  frontier.source_offer_id,
  frontier.gpu_model,
  frontier.gpu_raw_name,
  frontier.gpu_count,
  frontier.available_gpu_count_lower_bound,
  frontier.vram_gb,
  frontier.price_usd_gpu_hr,
  frontier.price_usd_instance_hr,
  frontier.country,
  frontier.region,
  frontier.is_spot,
  frontier.is_secure,
  frontier.source_availability_status,
  eligible.listing_id is not null as eligible_for_benchmark,
  coalesce(eligible.provider_rank = 1, false) as included,
  case
    when eligible.provider_rank = 1 then 'provider_floor'
    else null
  end as inclusion_reason,
  case
    when eligible.provider_rank = 1 then null
    when frontier.source_availability_status in (
      'spot_available',
      'spot_price_observed'
    ) then 'different_price_basis_spot'
    when frontier.source_availability_status = 'published_rate_future' then 'future_rate'
    when frontier.source_availability_status = 'published_rate_reserved' then 'committed_term_rate'
    when frontier.source_availability_status = 'published_rate_request' then 'request_price'
    when frontier.observation_kind = 'reference_price' then 'aggregated_reference_price'
    when frontier.observation_kind = 'spot_price' or coalesce(frontier.is_spot, false)
      then 'different_price_basis_spot'
    when frontier.source_availability_status not in (
      'available',
      'published_rate'
    ) then 'not_currently_available'
    when eligible.provider_rank > 1 then 'higher_same_provider_offer'
    else 'not_eligible'
  end as exclusion_reason,
  eligible.constituent_rank,
  eligible.provider_rank,
  coalesce(eligible.constituent_rank = 1, false) as is_floor_constituent,
  frontier.observed_at,
  frontier.raw_ref,
  frontier.has_raw_evidence,
  frontier.source_run_id,
  frontier.source_manifest_ref,
  frontier.source_normalized_ref,
  ${gold_run_id} as gold_run_id,
  ${calculated_at} as calculated_at
from frontier_offers frontier
left join eligible_ranked eligible
  on frontier.listing_id = eligible.listing_id
order by
  frontier.sort_order,
  included desc,
  eligible.constituent_rank,
  frontier.price_usd_gpu_hr
