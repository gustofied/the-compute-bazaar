"""Prime frontier-GPU offer history, lifecycle events, and shelf SQL."""

from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any


PRIME_FRONTIER_METHOD_VERSION = "prime_frontier_offer_market_v1"
PRIME_FRONTIER_SCOPE = "prime_secure_ondemand_frontier_all_shapes"
PRIME_FRONTIER_PRICE_INCREMENT = 0.25
PRIME_FRONTIER_SOURCE_URL = (
    "https://app.primeintellect.ai/dashboard/on-demand-gpus"
    "?image=ubuntu_22_cuda_12&security=Cheapest&pricing_type=Cheapest"
    "&location=Cheapest"
)
PRIME_FRONTIER_API_DOCS_URL = (
    "https://docs.primeintellect.ai/api-reference/check-gpu-availability"
)
PRIME_FRONTIER_PROVISION_DOCS_URL = (
    "https://docs.primeintellect.ai/api-reference/provision-gpu"
)


@dataclass(frozen=True)
class PrimeFrontierProduct:
    family_id: str
    label: str
    canonical_model: str
    api_gpu_type: str

    @property
    def market_url(self) -> str:
        return f"{PRIME_FRONTIER_SOURCE_URL}&gpu_type={self.api_gpu_type}&quantity=1"


PRIME_FRONTIER_PRODUCTS = (
    PrimeFrontierProduct("H100", "H100", "H100_80GB", "H100_80GB"),
    PrimeFrontierProduct("H200", "H200", "H200_141GB", "H200_141GB"),
    PrimeFrontierProduct("B200", "B200", "B200_180GB", "B200_180GB"),
    PrimeFrontierProduct("B300", "B300", "B300_288GB", "B300_262GB"),
)
PRIME_FRONTIER_PRODUCT_BY_FAMILY = {
    product.family_id: product for product in PRIME_FRONTIER_PRODUCTS
}

PRIME_FRONTIER_HISTORY_COLUMNS = (
    "listing_id",
    "provider_id",
    "provider",
    "source_offer_id",
    "gpu_family_id",
    "gpu_product_id",
    "gpu_model",
    "gpu_raw_name",
    "source_connector",
    "gpu_count",
    "available_gpu_count",
    "vram_gb",
    "price_usd_hr",
    "price_usd_instance_hr",
    "price_usd_gpu_hr",
    "currency",
    "country",
    "region",
    "region_id",
    "is_spot",
    "is_secure",
    "availability_status",
    "freshness_status",
    "gpu_socket",
    "stock_status",
    "price_is_variable",
    "minimum_executable_price_usd_hr",
    "required_resource_price_usd_hr",
    "price_basis",
    "observed_at",
    "raw_ref",
    "has_raw_evidence",
    "source_run_id",
    "source_manifest_ref",
    "source_normalized_ref",
    "calculated_at",
    "gold_run_id",
    "gold_observed_at",
    "gold_observed_date",
)


def prime_frontier_product_for_model(
    gpu_model: Any,
) -> PrimeFrontierProduct | None:
    model = str(gpu_model or "")
    for product in PRIME_FRONTIER_PRODUCTS:
        if model == product.canonical_model or model.startswith(
            f"{product.canonical_model}_x"
        ):
            return product
    return None


def normalize_prime_frontier_history(
    rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Keep one schema across historical Gold versions and four GPU families."""
    normalized: list[dict[str, Any]] = []
    for source in rows:
        if str(source.get("source_connector") or "") != "prime_intellect":
            continue
        product = prime_frontier_product_for_model(source.get("gpu_model"))
        if product is None:
            continue
        row = {column: source.get(column) for column in PRIME_FRONTIER_HISTORY_COLUMNS}
        row["gpu_family_id"] = product.family_id
        row["source_connector"] = "prime_intellect"
        row["price_basis"] = (
            source.get("price_basis") or "provider_reported_gpu_base_rate"
        )
        row["gold_observed_at"] = (
            source.get("gold_observed_at")
            or source.get("calculated_at")
            or source.get("observed_at")
        )
        row["gold_observed_date"] = source.get("gold_observed_date") or _date_part(
            row["gold_observed_at"]
        )
        normalized.append(row)

    deduplicated = {
        (str(row.get("gold_run_id") or ""), str(row.get("listing_id") or "")): row
        for row in normalized
        if row.get("gold_run_id") and row.get("listing_id")
    }
    return sorted(
        deduplicated.values(),
        key=lambda row: (
            str(row.get("gold_observed_at") or ""),
            str(row.get("gold_run_id") or ""),
            str(row.get("gpu_family_id") or ""),
            str(row.get("provider") or ""),
            float(row.get("price_usd_gpu_hr") or math.inf),
            str(row.get("listing_id") or ""),
        ),
    )


def build_prime_frontier_offer_events(
    history_rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Classify observable configuration changes without inventing fills."""
    normalized = normalize_prime_frontier_history(history_rows)
    run_keys = sorted(
        {
            (
                str(row.get("gold_observed_at") or ""),
                str(row.get("gold_run_id") or ""),
            )
            for row in normalized
        }
    )
    snapshots: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in normalized:
        snapshots[
            (
                str(row.get("gpu_family_id") or ""),
                str(row.get("gold_observed_at") or ""),
                str(row.get("gold_run_id") or ""),
            )
        ].append(row)

    events: list[dict[str, Any]] = []
    for product in PRIME_FRONTIER_PRODUCTS:
        previous_key: tuple[str, str] | None = None
        previous_rows: dict[str, dict[str, Any]] = {}
        for observed_at, run_id in run_keys:
            snapshot_rows = snapshots.get((product.family_id, observed_at, run_id), [])
            current_rows = {
                str(row["listing_id"]): row
                for row in snapshot_rows
                if _is_eligible_offer(row)
            }
            previous_observed_at = previous_key[0] if previous_key else None
            previous_run_id = previous_key[1] if previous_key else None
            comparison_gap_seconds = _seconds_between(previous_observed_at, observed_at)
            identities = sorted(set(previous_rows) | set(current_rows))
            for listing_id in identities:
                previous = previous_rows.get(listing_id)
                current = current_rows.get(listing_id)
                event_type = _event_type(previous, current)
                before = _float_or_none(
                    previous.get("price_usd_gpu_hr") if previous else None
                )
                after = _float_or_none(
                    current.get("price_usd_gpu_hr") if current else None
                )
                active = current or previous
                if active is None:
                    continue
                event_price = after if after is not None else before
                delta = (
                    after - before if before is not None and after is not None else None
                )
                delta_pct = (
                    delta / before
                    if delta is not None and before not in {None, 0}
                    else None
                )
                event_id = hashlib.sha256(
                    (f"{run_id}|{product.family_id}|{listing_id}|{event_type}").encode(
                        "utf-8"
                    )
                ).hexdigest()[:24]
                events.append(
                    {
                        "event_id": event_id,
                        "event_type": event_type,
                        "event_label": _event_label(event_type),
                        "listing_id": listing_id,
                        "provider": active.get("provider"),
                        "source_connector": "prime_intellect",
                        "gpu_family_id": product.family_id,
                        "gpu_model": active.get("gpu_model"),
                        "gpu_count": active.get("gpu_count"),
                        "gpu_socket": active.get("gpu_socket"),
                        "region": active.get("region"),
                        "stock_status_before": (
                            previous.get("stock_status") if previous else None
                        ),
                        "stock_status_after": (
                            current.get("stock_status") if current else None
                        ),
                        "price_before_usd_gpu_hr": before,
                        "price_after_usd_gpu_hr": after,
                        "price_delta_usd_gpu_hr": delta,
                        "price_delta_fraction": delta_pct,
                        "price_level_usd_gpu_hr": (
                            _price_level(event_price)
                            if event_price is not None
                            else None
                        ),
                        "previous_observed_at": previous_observed_at,
                        "observed_at": observed_at,
                        "comparison_gap_seconds": comparison_gap_seconds,
                        "previous_gold_run_id": previous_run_id,
                        "gold_run_id": run_id,
                        "methodology_version": PRIME_FRONTIER_METHOD_VERSION,
                        "source_url": product.market_url,
                        "notes": (
                            "Observable availability event; leaving public "
                            "availability is not evidence of a rental, fill, "
                            "or cancellation."
                        ),
                    }
                )
            previous_rows = current_rows
            previous_key = (observed_at, run_id)
    return events


def prime_frontier_reference_history_sql() -> str:
    """DataFusion SQL for provider-balanced Prime frontier references."""
    return f"""
with eligible as (
  select
    *,
    row_number() over(
      partition by gold_run_id, gpu_family_id, provider
      order by price_usd_gpu_hr asc, gpu_count asc, listing_id asc
    ) as provider_rank
  from fact_prime_frontier_offer_history
  where source_connector = 'prime_intellect'
    and availability_status = 'available'
    and price_usd_gpu_hr > 0
    and coalesce(is_spot, false) = false
    and coalesce(is_secure, false) = true
),
provider_floors as (
  select *
  from eligible
  where provider_rank = 1
),
reference_base as (
  select
    gold_run_id,
    gpu_family_id,
    max(gpu_product_id) as gpu_product_family,
    max(gold_observed_at) as gold_observed_at,
    max(gold_observed_date) as gold_observed_date,
    median(price_usd_gpu_hr) as reference_usd_gpu_hr,
    avg(price_usd_gpu_hr) as provider_floor_mean_usd_gpu_hr,
    percentile_cont(0.25) within group (
      order by price_usd_gpu_hr
    ) as provider_floor_p25_usd_gpu_hr,
    percentile_cont(0.75) within group (
      order by price_usd_gpu_hr
    ) as provider_floor_p75_usd_gpu_hr,
    min(price_usd_gpu_hr) as best_usd_gpu_hr,
    max(price_usd_gpu_hr) as highest_provider_floor_usd_gpu_hr,
    count(*) as provider_count,
    count(distinct country) as country_count,
    sum(case when coalesce(price_is_variable, false) then 1 else 0 end)
      as variable_price_provider_count,
    case
      when count(minimum_executable_price_usd_hr) = count(*)
      then median(minimum_executable_price_usd_hr / gpu_count)
      else cast(null as double)
    end as minimum_executable_reference_usd_gpu_hr,
    max(observed_at) as latest_source_observed_at
  from provider_floors
  group by gold_run_id, gpu_family_id
),
configuration_counts as (
  select
    gold_run_id,
    gpu_family_id,
    count(*) as configuration_count,
    sum(case when gpu_count = 1 then 1 else 0 end)
      as single_gpu_configuration_count,
    count(distinct gpu_socket) as socket_count
  from eligible
  group by gold_run_id, gpu_family_id
),
low_price_breadth as (
  select
    floors.gold_run_id,
    floors.gpu_family_id,
    count(*) as low_price_provider_count
  from provider_floors floors
  join reference_base reference
    on floors.gold_run_id = reference.gold_run_id
   and floors.gpu_family_id = reference.gpu_family_id
  where floors.price_usd_gpu_hr <= reference.reference_usd_gpu_hr * 1.10
  group by floors.gold_run_id, floors.gpu_family_id
)
select
  concat(
    'PRIME-', reference.gpu_family_id, '-OFFER-REFERENCE:',
    reference.gold_run_id
  ) as offer_reference_id,
  concat('PRIME-', reference.gpu_family_id, '-OFFER-REFERENCE')
    as offer_reference_symbol,
  '{PRIME_FRONTIER_SCOPE}' as reference_scope,
  reference.gpu_family_id,
  reference.gpu_product_family,
  'USD_GPU_HOUR' as unit,
  'provider_reported_gpu_base_rate' as price_basis,
  reference.reference_usd_gpu_hr,
  reference.minimum_executable_reference_usd_gpu_hr,
  reference.provider_floor_mean_usd_gpu_hr,
  reference.provider_floor_p25_usd_gpu_hr,
  reference.provider_floor_p75_usd_gpu_hr,
  reference.best_usd_gpu_hr,
  reference.highest_provider_floor_usd_gpu_hr,
  reference.provider_count,
  configurations.configuration_count,
  configurations.single_gpu_configuration_count,
  configurations.socket_count,
  reference.country_count,
  reference.variable_price_provider_count,
  breadth.low_price_provider_count,
  case when reference.provider_count >= 3 then 'observed' else 'indicative' end
    as status,
  reference.latest_source_observed_at,
  reference.gold_run_id,
  reference.gold_observed_at,
  reference.gold_observed_date,
  '{PRIME_FRONTIER_METHOD_VERSION}' as methodology_version
from reference_base reference
join configuration_counts configurations
  on reference.gold_run_id = configurations.gold_run_id
 and reference.gpu_family_id = configurations.gpu_family_id
join low_price_breadth breadth
  on reference.gold_run_id = breadth.gold_run_id
 and reference.gpu_family_id = breadth.gpu_family_id
order by
  reference.gold_observed_at,
  reference.gold_run_id,
  reference.gpu_family_id
"""


def prime_frontier_ladder_sql(*, current_gold_run_id: str) -> str:
    """DataFusion SQL for current benchmark-centered offer-level breadth."""
    increment = PRIME_FRONTIER_PRICE_INCREMENT
    run_id = _sql_literal(current_gold_run_id)
    return f"""
with latest_reference as (
  select *
  from fact_prime_frontier_offer_reference_history
  where gold_run_id = {run_id}
),
benchmark_current as (
  select
    benchmark_family_id as gpu_family_id,
    benchmark_usd_gpu_hr as market_benchmark_usd_gpu_hr,
    provider_floor_p25_usd_gpu_hr as market_benchmark_p25_usd_gpu_hr,
    provider_floor_p75_usd_gpu_hr as market_benchmark_p75_usd_gpu_hr,
    provider_count as market_benchmark_provider_count
  from fact_benchmark_values
),
reference_with_benchmark as (
  select
    reference.*,
    benchmark.market_benchmark_usd_gpu_hr,
    benchmark.market_benchmark_p25_usd_gpu_hr,
    benchmark.market_benchmark_p75_usd_gpu_hr,
    benchmark.market_benchmark_provider_count,
    coalesce(
      benchmark.market_benchmark_usd_gpu_hr,
      reference.reference_usd_gpu_hr
    ) as center_usd_gpu_hr
  from latest_reference reference
  left join benchmark_current benchmark
    on reference.gpu_family_id = benchmark.gpu_family_id
),
current_offers as (
  select
    history.*,
    round(history.price_usd_gpu_hr / {increment}) * {increment}
      as price_level_usd_gpu_hr
  from fact_prime_frontier_offer_history history
  join reference_with_benchmark reference
    on history.gold_run_id = reference.gold_run_id
   and history.gpu_family_id = reference.gpu_family_id
  where history.availability_status = 'available'
    and history.price_usd_gpu_hr > 0
    and coalesce(history.is_spot, false) = false
    and coalesce(history.is_secure, false) = true
),
offer_levels as (
  select
    gpu_family_id,
    price_level_usd_gpu_hr,
    count(*) as configuration_count,
    count(distinct provider) as provider_count,
    sum(case when gpu_count = 1 then 1 else 0 end)
      as single_gpu_configuration_count,
    min(price_usd_gpu_hr) as minimum_offer_usd_gpu_hr,
    max(price_usd_gpu_hr) as maximum_offer_usd_gpu_hr
  from current_offers
  group by gpu_family_id, price_level_usd_gpu_hr
),
latest_events as (
  select events.*
  from fact_prime_frontier_offer_events events
  join reference_with_benchmark reference
    on events.gold_run_id = reference.gold_run_id
   and events.gpu_family_id = reference.gpu_family_id
),
event_levels as (
  select
    gpu_family_id,
    price_level_usd_gpu_hr,
    sum(case when event_type = 'entered' then 1 else 0 end) as entered_count,
    sum(
      case when event_type in ('repriced_up', 'repriced_down') then 1 else 0 end
    ) as repriced_count,
    sum(
      case when event_type = 'left_availability' then 1 else 0 end
    ) as left_availability_count,
    sum(
      case when event_type = 'stock_status_changed' then 1 else 0 end
    ) as stock_status_changed_count,
    sum(case when event_type = 'remained' then 1 else 0 end) as remained_count
  from latest_events
  where price_level_usd_gpu_hr is not null
  group by gpu_family_id, price_level_usd_gpu_hr
),
reference_grid as (
  select
    reference.gpu_family_id,
    round(reference.center_usd_gpu_hr / {increment}) * {increment}
      + offsets.offset * {increment} as price_level_usd_gpu_hr
  from reference_with_benchmark reference
  cross join (
    values (-6), (-5), (-4), (-3), (-2), (-1), (0),
           (1), (2), (3), (4), (5), (6)
  ) as offsets(offset)
),
all_levels as (
  select gpu_family_id, price_level_usd_gpu_hr from reference_grid
  union
  select gpu_family_id, price_level_usd_gpu_hr from offer_levels
  union
  select gpu_family_id, price_level_usd_gpu_hr from event_levels
),
joined as (
  select
    levels.gpu_family_id,
    levels.price_level_usd_gpu_hr,
    coalesce(offers.configuration_count, 0) as configuration_count,
    coalesce(offers.provider_count, 0) as provider_count,
    coalesce(offers.single_gpu_configuration_count, 0)
      as single_gpu_configuration_count,
    offers.minimum_offer_usd_gpu_hr,
    offers.maximum_offer_usd_gpu_hr,
    coalesce(events.entered_count, 0) as entered_count,
    coalesce(events.repriced_count, 0) as repriced_count,
    coalesce(events.left_availability_count, 0) as left_availability_count,
    coalesce(events.stock_status_changed_count, 0)
      as stock_status_changed_count,
    coalesce(events.remained_count, 0) as remained_count,
    reference.reference_usd_gpu_hr,
    reference.market_benchmark_usd_gpu_hr,
    reference.market_benchmark_p25_usd_gpu_hr,
    reference.market_benchmark_p75_usd_gpu_hr,
    reference.market_benchmark_provider_count,
    levels.price_level_usd_gpu_hr - reference.reference_usd_gpu_hr
      as distance_from_prime_reference_usd_gpu_hr,
    levels.price_level_usd_gpu_hr - reference.center_usd_gpu_hr
      as distance_from_market_benchmark_usd_gpu_hr,
    case
      when reference.market_benchmark_usd_gpu_hr > 0
      then levels.price_level_usd_gpu_hr
        / reference.market_benchmark_usd_gpu_hr - 1
      else cast(null as double)
    end as premium_to_market_benchmark_fraction,
    abs(levels.price_level_usd_gpu_hr - reference.reference_usd_gpu_hr)
      <= {increment / 2} as is_prime_reference_level,
    abs(levels.price_level_usd_gpu_hr - reference.center_usd_gpu_hr)
      <= {increment / 2} as is_market_benchmark_level,
    reference.gold_run_id,
    reference.gold_observed_at,
    reference.status,
    reference.methodology_version
  from all_levels levels
  join reference_with_benchmark reference
    on levels.gpu_family_id = reference.gpu_family_id
  left join offer_levels offers
    on levels.gpu_family_id = offers.gpu_family_id
   and levels.price_level_usd_gpu_hr = offers.price_level_usd_gpu_hr
  left join event_levels events
    on levels.gpu_family_id = events.gpu_family_id
   and levels.price_level_usd_gpu_hr = events.price_level_usd_gpu_hr
)
select
  *,
  row_number() over(
    partition by gpu_family_id
    order by price_level_usd_gpu_hr desc
  ) as price_level_rank
from joined
order by gpu_family_id, price_level_usd_gpu_hr desc
"""


def _is_eligible_offer(row: Mapping[str, Any]) -> bool:
    price = _float_or_none(row.get("price_usd_gpu_hr"))
    return bool(
        price is not None
        and price > 0
        and str(row.get("availability_status") or "") == "available"
        and row.get("is_spot") is not True
        and row.get("is_secure") is True
    )


def _event_type(
    previous: Mapping[str, Any] | None,
    current: Mapping[str, Any] | None,
) -> str:
    if previous is None:
        return "entered"
    if current is None:
        return "left_availability"
    before = _float_or_none(previous.get("price_usd_gpu_hr"))
    after = _float_or_none(current.get("price_usd_gpu_hr"))
    if (
        before is not None
        and after is not None
        and not math.isclose(before, after, rel_tol=1e-9, abs_tol=1e-9)
    ):
        return "repriced_up" if after > before else "repriced_down"
    if str(previous.get("stock_status") or "") != str(
        current.get("stock_status") or ""
    ):
        return "stock_status_changed"
    return "remained"


def _event_label(event_type: str) -> str:
    return {
        "entered": "Entered availability",
        "left_availability": "Left availability",
        "repriced_up": "Repriced higher",
        "repriced_down": "Repriced lower",
        "stock_status_changed": "Stock label changed",
        "remained": "Remained available",
    }[event_type]


def _price_level(value: float) -> float:
    return (
        math.floor(value / PRIME_FRONTIER_PRICE_INCREMENT + 0.5)
        * PRIME_FRONTIER_PRICE_INCREMENT
    )


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _date_part(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)[:10] or None


def _seconds_between(start: Any, end: Any) -> float | None:
    if not start or not end:
        return None
    try:
        left = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        right = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (right - left).total_seconds()


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
