"""Build bronze, silver, and gold sandbox-cost products with DataFusion."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

from the_compute_bazaar.prices.datafusion import query_tables
from the_compute_bazaar.prices.storage import (
    read_json,
    write_bytes,
    write_json,
    write_parquet_rows,
)


EVIDENCE_ROOT = Path(__file__).with_name("evidence")
PRICE_EVIDENCE = EVIDENCE_ROOT / "hourly-price-observations.json"
BENCHMARK_EVIDENCE = EVIDENCE_ROOT / "benchmark-observations.json"
SOURCE_MANIFEST = EVIDENCE_ROOT / "source-manifest.json"

TARGET_SHAPE = {"vcpus": 4, "memory_gib": 8, "disk_gb": 40}
FIXED_COHORT = "2026"
SANDBOX_RATE_METHODOLOGY = "advertised_fixed_cohort_median_iqr_v2"
FIXED_RATE_QUERY_ID = "sandbox_fixed_cohort_rate_v2"
PRICE_EVENTS_QUERY_ID = "sandbox_rate_card_events_v1"
CURRENT_RATES_QUERY_ID = "sandbox_current_rate_cross_section_v1"
WORKLOAD_BATCH_QUERY_ID = "sandbox_workload_batch_history_v2"
WORKLOAD_REPLICATE_QUERY_ID = "sandbox_workload_latest_replicates_v2"
WORKLOAD_PHASE_QUERY_ID = "sandbox_workload_latest_phases_v1"
WORKLOAD_PHASE_SUMMARY_QUERY_ID = "sandbox_workload_phase_summary_v1"
WORKLOAD_SUMMARY_QUERY_ID = "sandbox_workload_service_summary_v2"
GPU_COMPARISON_MIN_PROVIDERS = 10
GPU_DAILY_QUERY_ID = "h100_daily_broad_coverage_v1"
GPU_ELIGIBLE_QUERY_ID = "h100_broad_coverage_prints_v1"
COMBINED_QUERY_ID = "sandbox_gpu_cpu_common_start_v3"
NUMERIC_DECIMAL_PLACES = 12

RUNTIME_PRICE_SERIES = {
    "blaxel": "blaxel",
    "daytona-vm": "daytona",
    "e2b": "e2b",
    "modal-gvisor": "modal",
    "modal-vm": "modal",
    "novita": "novita",
}

RATE_METERING = {
    "beam": {
        "processor_meter": "reserved_capacity",
        "memory_meter": "reserved_capacity",
        "billing_basis_label": "physical cores and memory while running",
    },
    "blaxel": {
        "processor_meter": "memory_coupled",
        "memory_meter": "active_runtime",
        "billing_basis_label": "active runtime, priced by allocated memory",
    },
    "daytona": {
        "processor_meter": "reserved_capacity",
        "memory_meter": "reserved_capacity",
        "billing_basis_label": "reserved CPU and memory while running",
    },
    "e2b": {
        "processor_meter": "reserved_capacity",
        "memory_meter": "reserved_capacity",
        "billing_basis_label": "reserved CPU and memory while running",
    },
    "fly-sprites": {
        "processor_meter": "actual_usage",
        "memory_meter": "actual_usage",
        "billing_basis_label": "actual CPU and memory use",
    },
    "freestyle": {
        "processor_meter": "reserved_capacity",
        "memory_meter": "reserved_capacity",
        "billing_basis_label": "VM CPU and memory while running",
    },
    "modal": {
        "processor_meter": "max_requested_or_actual",
        "memory_meter": "max_requested_or_actual",
        "billing_basis_label": "higher of requested or actual use",
    },
    "novita": {
        "processor_meter": "reserved_capacity",
        "memory_meter": "reserved_capacity",
        "billing_basis_label": "allocated CPU and memory while running",
    },
    "runloop": {
        "processor_meter": "reserved_capacity",
        "memory_meter": "reserved_capacity",
        "billing_basis_label": "devbox CPU and memory while active",
    },
    "sailboxes": {
        "processor_meter": "actual_usage",
        "memory_meter": "actual_usage",
        "billing_basis_label": "actual CPU and memory use",
    },
    "vercel": {
        "processor_meter": "active_usage",
        "memory_meter": "reserved_capacity",
        "billing_basis_label": "active CPU and provisioned memory",
    },
}

PRICE_FIELDS = {
    "series_order",
    "point_order",
    "series_id",
    "series_label",
    "observed_date",
    "price_usd_per_hour",
    "processor_quantity",
    "processor_unit",
    "processor_rate_usd_per_unit_hour",
    "memory_gib",
    "memory_rate_usd_per_gib_hour",
    "date_role",
    "change_precision",
    "source_role",
    "index_eligible",
    "index_cohort",
    "evidence_class",
    "source_label",
    "source_url",
    "note",
    "color",
}

BATCH_FIELDS = {
    "series_order",
    "point_order",
    "series_id",
    "series_label",
    "observed_date",
    "generated_at",
    "runtime_seconds",
    "hourly_price_usd",
    "estimated_cost_usd",
    "price_scope",
    "vcpus",
    "memory_gib",
    "disk_gb",
    "observed_vcpus",
    "observed_memory_gib",
    "observed_disk_gb",
    "cpu_model",
    "virtualization",
    "country",
    "region",
    "city",
    "egress_asn",
    "job_parts",
    "benchmark_run_id",
    "source_run_sha",
    "workload_app_version",
    "task_signature",
    "methodology_id",
    "benchmark_source_url",
    "price_date",
    "price_source_url",
    "cost_basis",
    "lifecycle_included",
    "workload_gap_count",
    "replicate_count",
    "replicate_data_available",
    "observation_level",
    "runtime_basis",
    "note",
    "color",
}

REPLICATE_FIELDS = {
    "series_order",
    "series_id",
    "series_label",
    "observed_date",
    "generated_at",
    "runtime_seconds",
    "hourly_price_usd",
    "estimated_cost_usd",
    "price_scope",
    "vcpus",
    "memory_gib",
    "disk_gb",
    "observed_vcpus",
    "observed_memory_gib",
    "observed_disk_gb",
    "cpu_model",
    "virtualization",
    "country",
    "region",
    "city",
    "egress_asn",
    "job_parts",
    "benchmark_run_id",
    "source_run_sha",
    "workload_app_version",
    "task_signature",
    "methodology_id",
    "benchmark_source_url",
    "price_date",
    "price_source_url",
    "cost_basis",
    "lifecycle_included",
    "workload_gap_count",
    "color",
    "replicate_index",
    "task_count",
    "observation_level",
    "runtime_basis",
}

PHASE_FIELDS = {
    "series_order",
    "series_id",
    "series_label",
    "observed_date",
    "generated_at",
    "benchmark_run_id",
    "source_run_sha",
    "methodology_id",
    "workload_app_version",
    "task_signature",
    "replicate_index",
    "task_order",
    "task_id",
    "task_label",
    "runtime_seconds",
    "benchmark_source_url",
    "color",
}

RUN_METADATA_FIELDS = {
    "benchmark_run_id",
    "generated_at",
    "source_run_sha",
    "methodology_id",
    "workload_app_version",
    "task_signature",
    "target_vcpus",
    "target_memory_gib",
    "target_disk_gb",
    "task_count",
    "provider_result_count",
    "replicate_indexed",
    "runtime_basis",
    "lifecycle_included",
    "benchmark_source_url",
}

FIXED_RATE_SQL = f"""
with ordered_prices as (
  select
    *,
    lag(price_usd_per_hour) over (
      partition by series_id
      order by cast(observed_date as date), point_order
    ) as previous_price_usd_per_hour
  from sandbox_hourly_prices
  where index_eligible = true
    and index_cohort = '{FIXED_COHORT}'
),
event_dates as (
  select cast('2026-01-01' as date) as observed_date
  union
  select distinct cast(observed_date as date) as observed_date
  from ordered_prices
  where cast(observed_date as date) >= cast('2026-01-01' as date)
    and previous_price_usd_per_hour is not null
    and abs(price_usd_per_hour - previous_price_usd_per_hour) > 0.000000001
),
members as (
  select distinct series_id
  from sandbox_hourly_prices
  where index_eligible = true
    and index_cohort = '{FIXED_COHORT}'
),
ranked as (
  select
    dates.observed_date,
    prices.series_id,
    prices.series_label,
    prices.price_usd_per_hour,
    cast(prices.observed_date as date) as source_price_date,
    prices.source_url,
    row_number() over (
      partition by dates.observed_date, prices.series_id
      order by cast(prices.observed_date as date) desc, prices.point_order desc
    ) as recency_rank
  from event_dates dates
  cross join members
  join sandbox_hourly_prices prices
    on prices.series_id = members.series_id
   and cast(prices.observed_date as date) <= dates.observed_date
),
current_members as (
  select *
  from ranked
  where recency_rank = 1
)
select
  observed_date,
  '{SANDBOX_RATE_METHODOLOGY}' as methodology_version,
  '{FIXED_COHORT}' as cohort_id,
  median(price_usd_per_hour) as median_usd_per_hour,
  avg(price_usd_per_hour) as average_usd_per_hour,
  percentile_cont(0.25) within group (
    order by price_usd_per_hour
  ) as p25_usd_per_hour,
  percentile_cont(0.75) within group (
    order by price_usd_per_hour
  ) as p75_usd_per_hour,
  count(*) as member_count,
  min(price_usd_per_hour) as minimum_usd_per_hour,
  max(price_usd_per_hour) as maximum_usd_per_hour
from current_members
group by observed_date
having count(*) = 8
order by observed_date
"""

PRICE_EVENTS_SQL = """
with ordered as (
  select
    *,
    lag(price_usd_per_hour) over (
      partition by series_id
      order by cast(observed_date as date), point_order
    ) as previous_price_usd_per_hour
  from sandbox_hourly_prices
  where index_eligible = true
)
select
  series_order,
  point_order,
  series_id,
  series_label,
  observed_date,
  previous_price_usd_per_hour,
  price_usd_per_hour,
  price_usd_per_hour - previous_price_usd_per_hour as price_change_usd_per_hour,
  (
    price_usd_per_hour / previous_price_usd_per_hour - 1.0
  ) * 100.0 as price_change_percent,
  date_role,
  change_precision,
  evidence_class,
  source_label,
  source_url,
  note,
  color
from ordered
where previous_price_usd_per_hour is not null
  and abs(price_usd_per_hour - previous_price_usd_per_hour) > 0.000000001
order by cast(observed_date as date), series_order, point_order
"""

CURRENT_RATES_SQL = f"""
with ranked as (
  select
    *,
    row_number() over (
      partition by series_id
      order by cast(observed_date as date) desc, point_order desc
    ) as recency_rank
  from sandbox_hourly_prices
  where index_eligible = true
)
select
  series_order,
  series_id,
  series_label,
  observed_date,
  price_usd_per_hour,
  processor_quantity,
  processor_unit,
  processor_rate_usd_per_unit_hour,
  memory_gib,
  memory_rate_usd_per_gib_hour,
  processor_meter,
  memory_meter,
  billing_basis_label,
  index_cohort = '{FIXED_COHORT}' as fixed_cohort_member,
  date_role,
  change_precision,
  evidence_class,
  source_label,
  source_url,
  note,
  color
from ranked
where recency_rank = 1
order by price_usd_per_hour, series_label
"""

WORKLOAD_BATCH_SQL = """
select *
from sandbox_benchmark_batches
order by series_order, generated_at, point_order
"""

WORKLOAD_LATEST_REPLICATES_SQL = """
with latest as (
  select max(generated_at) as generated_at
  from sandbox_benchmark_replicates
)
select replicates.*
from sandbox_benchmark_replicates replicates
join latest on latest.generated_at = replicates.generated_at
order by series_order, replicate_index
"""

WORKLOAD_LATEST_PHASES_SQL = """
with latest as (
  select max(generated_at) as generated_at
  from sandbox_benchmark_phases
)
select phases.*
from sandbox_benchmark_phases phases
join latest on latest.generated_at = phases.generated_at
order by series_order, replicate_index, task_order
"""

WORKLOAD_PHASE_SUMMARY_SQL = """
select
  series_order,
  series_id,
  series_label,
  color,
  task_order,
  task_id,
  task_label,
  count(*) as sample_count,
  median(runtime_seconds) as median_runtime_seconds,
  avg(runtime_seconds) as average_runtime_seconds,
  percentile_cont(0.25) within group (
    order by runtime_seconds
  ) as p25_runtime_seconds,
  percentile_cont(0.75) within group (
    order by runtime_seconds
  ) as p75_runtime_seconds,
  min(runtime_seconds) as minimum_runtime_seconds,
  max(runtime_seconds) as maximum_runtime_seconds
from sandbox_workload_latest_phases
group by
  series_order,
  series_id,
  series_label,
  color,
  task_order,
  task_id,
  task_label
order by series_order, task_order
"""

WORKLOAD_SUMMARY_SQL = """
with source_slots as (
  select count(distinct replicate_index) as source_replicate_slot_count
  from sandbox_workload_latest_replicates
),
summary as (
  select
    series_order,
    series_id,
    series_label,
    color,
    count(*) as result_count,
    max(source_slots.source_replicate_slot_count)
      as source_replicate_slot_count,
    max(source_slots.source_replicate_slot_count) - count(*)
      as incomplete_replicate_count,
    cast(count(*) as double)
      / cast(max(source_slots.source_replicate_slot_count) as double)
      as replicate_completion_ratio,
    count(distinct benchmark_run_id) as run_count,
    min(benchmark_run_id) as benchmark_run_id,
    min(methodology_id) as methodology_id,
    min(source_run_sha) as source_run_sha,
    min(generated_at) as first_generated_at,
    max(generated_at) as latest_generated_at,
    median(runtime_seconds) as median_runtime_seconds,
    avg(runtime_seconds) as average_runtime_seconds,
    percentile_cont(0.25) within group (
      order by runtime_seconds
    ) as p25_runtime_seconds,
    percentile_cont(0.75) within group (
      order by runtime_seconds
    ) as p75_runtime_seconds,
    min(runtime_seconds) as minimum_runtime_seconds,
    max(runtime_seconds) as maximum_runtime_seconds,
    median(estimated_cost_usd) as median_estimated_cost_usd,
    avg(estimated_cost_usd) as average_estimated_cost_usd,
    percentile_cont(0.25) within group (
      order by estimated_cost_usd
    ) as p25_estimated_cost_usd,
    percentile_cont(0.75) within group (
      order by estimated_cost_usd
    ) as p75_estimated_cost_usd,
    min(estimated_cost_usd) as minimum_estimated_cost_usd,
    max(estimated_cost_usd) as maximum_estimated_cost_usd
  from sandbox_workload_latest_replicates
  cross join source_slots
  group by series_order, series_id, series_label, color
)
select
  summary.series_order,
  summary.series_id,
  summary.series_label,
  summary.color,
  summary.result_count,
  summary.source_replicate_slot_count,
  summary.incomplete_replicate_count,
  summary.replicate_completion_ratio,
  summary.run_count,
  summary.benchmark_run_id,
  summary.methodology_id,
  summary.source_run_sha,
  summary.first_generated_at,
  summary.latest_generated_at,
  summary.median_runtime_seconds,
  summary.average_runtime_seconds,
  summary.p25_runtime_seconds,
  summary.p75_runtime_seconds,
  summary.minimum_runtime_seconds,
  summary.maximum_runtime_seconds,
  summary.median_estimated_cost_usd,
  summary.average_estimated_cost_usd,
  summary.p25_estimated_cost_usd,
  summary.p75_estimated_cost_usd,
  summary.minimum_estimated_cost_usd,
  summary.maximum_estimated_cost_usd,
  count(comparison.series_id) = 0 as on_lower_left_frontier
from summary
left join summary comparison
  on comparison.series_id != summary.series_id
 and comparison.median_runtime_seconds <= summary.median_runtime_seconds
 and comparison.median_estimated_cost_usd
   <= summary.median_estimated_cost_usd
 and (
   comparison.median_runtime_seconds < summary.median_runtime_seconds
   or comparison.median_estimated_cost_usd
     < summary.median_estimated_cost_usd
 )
group by
  summary.series_order,
  summary.series_id,
  summary.series_label,
  summary.color,
  summary.result_count,
  summary.source_replicate_slot_count,
  summary.incomplete_replicate_count,
  summary.replicate_completion_ratio,
  summary.run_count,
  summary.benchmark_run_id,
  summary.methodology_id,
  summary.source_run_sha,
  summary.first_generated_at,
  summary.latest_generated_at,
  summary.median_runtime_seconds,
  summary.average_runtime_seconds,
  summary.p25_runtime_seconds,
  summary.p75_runtime_seconds,
  summary.minimum_runtime_seconds,
  summary.maximum_runtime_seconds,
  summary.median_estimated_cost_usd,
  summary.average_estimated_cost_usd,
  summary.p25_estimated_cost_usd,
  summary.p75_estimated_cost_usd,
  summary.minimum_estimated_cost_usd,
  summary.maximum_estimated_cost_usd
order by median_runtime_seconds, median_estimated_cost_usd
"""

GPU_DAILY_COVERAGE_SQL = f"""
with compatible_gpu as (
  select
    gold_observed_at,
    cast(gold_observed_at as date) as observed_date,
    benchmark_family_id,
    benchmark_usd_gpu_hr,
    provider_count,
    included_offer_count,
    provider_floor_p25_usd_gpu_hr,
    provider_floor_p75_usd_gpu_hr,
    methodology_version,
    benchmark_basis,
    row_number() over (
      partition by gold_observed_at, benchmark_family_id
      order by calculated_at desc
    ) as duplicate_rank
  from gpu_benchmark_history
  where benchmark_family_id = 'H100'
    and methodology_version = 'advertised_provider_floor_median_v1'
    and benchmark_basis = 'advertised_hourly'
    and benchmark_usd_gpu_hr > 0
),
deduplicated as (
  select
    *
  from compatible_gpu
  where duplicate_rank = 1
),
daily_all as (
  select
    observed_date,
    count(*) as research_print_count,
    median(benchmark_usd_gpu_hr) as research_benchmark_usd_gpu_hr,
    min(provider_count) as minimum_provider_count,
    max(provider_count) as maximum_provider_count
  from deduplicated
  group by observed_date
),
daily_broad as (
  select
    observed_date,
    count(*) as eligible_print_count,
    median(benchmark_usd_gpu_hr) as benchmark_usd_gpu_hr,
    median(provider_floor_p25_usd_gpu_hr)
      as provider_floor_p25_usd_gpu_hr,
    median(provider_floor_p75_usd_gpu_hr)
      as provider_floor_p75_usd_gpu_hr,
    median(provider_count) as median_provider_count,
    min(provider_count) as eligible_minimum_provider_count,
    max(provider_count) as eligible_maximum_provider_count,
    median(included_offer_count) as median_included_offer_count
  from deduplicated
  where provider_count >= {GPU_COMPARISON_MIN_PROVIDERS}
  group by observed_date
)
select
  daily_all.observed_date,
  daily_all.research_print_count,
  daily_all.research_benchmark_usd_gpu_hr,
  daily_all.minimum_provider_count,
  daily_all.maximum_provider_count,
  coalesce(daily_broad.eligible_print_count, 0) as eligible_print_count,
  daily_broad.benchmark_usd_gpu_hr,
  daily_broad.provider_floor_p25_usd_gpu_hr,
  daily_broad.provider_floor_p75_usd_gpu_hr,
  daily_broad.median_provider_count,
  daily_broad.eligible_minimum_provider_count,
  daily_broad.eligible_maximum_provider_count,
  daily_broad.median_included_offer_count,
  daily_broad.eligible_print_count is not null as comparison_eligible,
  case
    when daily_broad.eligible_print_count is not null then null
    else 'provider_coverage_below_{GPU_COMPARISON_MIN_PROVIDERS}'
  end as exclusion_reason
from daily_all
left join daily_broad
  on daily_all.observed_date = daily_broad.observed_date
order by daily_all.observed_date
"""

GPU_ELIGIBLE_HISTORY_SQL = f"""
with compatible_gpu as (
  select
    gold_observed_at,
    cast(gold_observed_at as date) as observed_date,
    benchmark_family_id,
    benchmark_usd_gpu_hr,
    provider_count,
    included_offer_count,
    provider_floor_p25_usd_gpu_hr,
    provider_floor_p75_usd_gpu_hr,
    methodology_version,
    benchmark_basis,
    calculated_at,
    row_number() over (
      partition by gold_observed_at, benchmark_family_id
      order by calculated_at desc
    ) as duplicate_rank
  from gpu_benchmark_history
  where benchmark_family_id = 'H100'
    and methodology_version = 'advertised_provider_floor_median_v1'
    and benchmark_basis = 'advertised_hourly'
    and benchmark_usd_gpu_hr > 0
)
select
  gold_observed_at,
  observed_date,
  benchmark_family_id,
  benchmark_usd_gpu_hr,
  provider_count,
  included_offer_count,
  provider_floor_p25_usd_gpu_hr,
  provider_floor_p75_usd_gpu_hr,
  methodology_version,
  benchmark_basis,
  calculated_at
from compatible_gpu
where duplicate_rank = 1
  and provider_count >= {GPU_COMPARISON_MIN_PROVIDERS}
order by gold_observed_at
"""

COMBINED_COMMON_START_SQL = """
with joined as (
  select
    gpu.gold_observed_at,
    gpu.observed_date,
    gpu.benchmark_usd_gpu_hr,
    gpu.provider_count,
    gpu.included_offer_count,
    gpu.provider_floor_p25_usd_gpu_hr,
    gpu.provider_floor_p75_usd_gpu_hr,
    gpu.methodology_version as gpu_methodology_version,
    gpu.benchmark_basis as gpu_benchmark_basis,
    sandbox.observed_date as sandbox_price_date,
    sandbox.median_usd_per_hour as sandbox_median_usd_per_hour,
    sandbox.p25_usd_per_hour as sandbox_p25_usd_per_hour,
    sandbox.p75_usd_per_hour as sandbox_p75_usd_per_hour,
    sandbox.member_count as sandbox_member_count,
    row_number() over (
      partition by gpu.gold_observed_at
      order by sandbox.observed_date desc
    ) as sandbox_recency_rank
  from gpu_h100_eligible_history gpu
  join sandbox_fixed_rate sandbox
    on cast(sandbox.observed_date as date) <= gpu.observed_date
),
comparable as (
  select *
  from joined
  where sandbox_recency_rank = 1
),
baseline_ranked as (
  select
    *,
    row_number() over (order by gold_observed_at) as baseline_rank
  from comparable
),
baseline as (
  select
    benchmark_usd_gpu_hr as first_gpu_value,
    sandbox_median_usd_per_hour as first_sandbox_value,
    gold_observed_at as common_start_at
  from baseline_ranked
  where baseline_rank = 1
)
select
  comparable.gold_observed_at,
  comparable.observed_date,
  baseline.common_start_at,
  comparable.benchmark_usd_gpu_hr,
  comparable.provider_count,
  comparable.included_offer_count,
  comparable.provider_floor_p25_usd_gpu_hr,
  comparable.provider_floor_p75_usd_gpu_hr,
  comparable.gpu_methodology_version,
  comparable.gpu_benchmark_basis,
  comparable.sandbox_price_date,
  comparable.sandbox_median_usd_per_hour,
  comparable.sandbox_p25_usd_per_hour,
  comparable.sandbox_p75_usd_per_hour,
  comparable.sandbox_member_count,
  comparable.benchmark_usd_gpu_hr
    / comparable.sandbox_median_usd_per_hour
      as sandbox_hours_per_h100_gpu_hour,
  comparable.benchmark_usd_gpu_hr
    / baseline.first_gpu_value * 100.0 as gpu_base_100,
  comparable.provider_floor_p25_usd_gpu_hr
    / baseline.first_gpu_value * 100.0 as gpu_p25_base_100,
  comparable.provider_floor_p75_usd_gpu_hr
    / baseline.first_gpu_value * 100.0 as gpu_p75_base_100,
  comparable.sandbox_median_usd_per_hour
    / baseline.first_sandbox_value * 100.0 as sandbox_base_100,
  comparable.sandbox_p25_usd_per_hour
    / baseline.first_sandbox_value * 100.0 as sandbox_p25_base_100,
  comparable.sandbox_p75_usd_per_hour
    / baseline.first_sandbox_value * 100.0 as sandbox_p75_base_100
from comparable
cross join baseline
order by comparable.gold_observed_at
"""

GOLD_QUERIES = {
    "hourly-prices": """
select *
from sandbox_hourly_price_series
order by series_order, observed_date, point_order
""",
    "price-events": """
select *
from sandbox_price_events
order by observed_date, series_order, point_order
""",
    "current-rates": """
select *
from sandbox_current_rates
order by price_usd_per_hour, series_label
""",
    "fixed-rate": """
select *
from sandbox_fixed_rate
order by observed_date
""",
    "workload-batch-history": """
select *
from sandbox_workload_batch_history
order by series_order, generated_at, point_order
""",
    "workload-latest-replicates": """
select *
from sandbox_workload_latest_replicates
order by series_order, replicate_index
""",
    "workload-latest-phases": """
select *
from sandbox_workload_latest_phases
order by series_order, replicate_index, task_order
""",
    "workload-phase-summary": """
select *
from sandbox_workload_phase_summary
order by series_order, task_order
""",
    "workload-summary": """
select *
from sandbox_workload_service_summary
order by median_runtime_seconds, median_estimated_cost_usd
""",
    "gpu-daily-coverage": """
select *
from gpu_h100_daily_coverage
order by observed_date
""",
    "gpu-eligible-history": """
select *
from gpu_h100_eligible_history
order by gold_observed_at
""",
    "combined-common-start": """
select *
from sandbox_gpu_cpu_common_start
order by gold_observed_at
""",
}


@dataclass(frozen=True)
class SandboxCostBuild:
    build_id: str
    output_root: str
    manifest_ref: str
    public_ref: str | None
    table_refs: dict[str, str]
    row_counts: dict[str, int]


def validate_evidence(
    *,
    price_path: Path = PRICE_EVIDENCE,
    benchmark_path: Path = BENCHMARK_EVIDENCE,
    source_manifest_path: Path = SOURCE_MANIFEST,
) -> dict[str, Any]:
    """Validate formulas, matching rules, uniqueness, shape, and source retention."""
    prices_payload = _read_local_json(price_path)
    benchmarks_payload = _read_local_json(benchmark_path)
    source_manifest = _read_local_json(source_manifest_path)
    _require_schema(
        prices_payload,
        "sandbox_hourly_price_evidence_v1",
        price_path,
    )
    _require_schema(
        benchmarks_payload,
        "sandbox_benchmark_observation_v2",
        benchmark_path,
    )
    _require_schema(
        source_manifest,
        "sandbox_source_manifest_v1",
        source_manifest_path,
    )

    prices = _validate_prices(prices_payload.get("rows"))
    batches = _validate_batches(benchmarks_payload.get("batch_rows"), prices)
    replicates = _validate_replicates(
        benchmarks_payload.get("replicate_rows"),
        prices,
        batches,
    )
    phases = _validate_phases(
        benchmarks_payload.get("phase_rows"),
        replicates,
    )
    run_metadata = _validate_run_metadata(
        benchmarks_payload.get("run_metadata"),
        batches,
        replicates,
    )
    _validate_source_manifest(source_manifest, batches)

    return {
        "price_observation_count": len(prices),
        "price_service_count": len({row["series_id"] for row in prices}),
        "benchmark_batch_count": len(batches),
        "benchmark_replicate_count": len(replicates),
        "benchmark_phase_count": len(phases),
        "benchmark_service_count": len({row["series_id"] for row in batches}),
        "benchmark_run_count": len({row["benchmark_run_id"] for row in batches}),
        "benchmark_calendar_day_count": len(
            {row["observed_date"] for row in batches}
        ),
        "benchmark_methodology_count": len(
            {row["methodology_id"] for row in run_metadata}
        ),
        "latest_replicate_run_id": max(
            run_metadata,
            key=lambda row: row["generated_at"],
        )["benchmark_run_id"],
        "fixed_members": sorted(
            {
                row["series_id"]
                for row in prices
                if row["index_cohort"] == FIXED_COHORT
            }
        ),
        "source_file_count": len(source_manifest["files"]),
    }


def build_sandbox_cost(
    *,
    output_root: str = "data/sandbox-cost",
    dashboard_output_root: str | None = None,
    gpu_history_ref: str | None = None,
    price_path: Path = PRICE_EVIDENCE,
    benchmark_path: Path = BENCHMARK_EVIDENCE,
    source_manifest_path: Path = SOURCE_MANIFEST,
) -> SandboxCostBuild:
    """Build deterministic bronze, silver, gold, and optional public JSON."""
    summary = validate_evidence(
        price_path=price_path,
        benchmark_path=benchmark_path,
        source_manifest_path=source_manifest_path,
    )
    prices_payload = _read_local_json(price_path)
    benchmarks_payload = _read_local_json(benchmark_path)
    source_manifest = _read_local_json(source_manifest_path)
    price_rows = _validate_prices(prices_payload["rows"])
    batch_rows = list(benchmarks_payload["batch_rows"])
    replicate_rows = list(benchmarks_payload["replicate_rows"])
    phase_rows = list(benchmarks_payload["phase_rows"])
    run_metadata = list(benchmarks_payload["run_metadata"])

    bronze_refs = {
        "hourly_price_evidence": _join(
            output_root, "bronze/hourly-price-evidence.json"
        ),
        "benchmark_evidence": _join(
            output_root, "bronze/benchmark-evidence.json"
        ),
        "source_manifest": _join(output_root, "bronze/source-manifest.json"),
    }
    write_json(bronze_refs["hourly_price_evidence"], prices_payload)
    write_json(bronze_refs["benchmark_evidence"], benchmarks_payload)
    write_json(bronze_refs["source_manifest"], source_manifest)

    silver_refs = {
        "sandbox_hourly_prices": _join(
            output_root, "silver/sandbox_hourly_prices.parquet"
        ),
        "sandbox_benchmark_batches": _join(
            output_root, "silver/sandbox_benchmark_batches.parquet"
        ),
        "sandbox_benchmark_replicates": _join(
            output_root, "silver/sandbox_benchmark_replicates.parquet"
        ),
        "sandbox_benchmark_phases": _join(
            output_root, "silver/sandbox_benchmark_phases.parquet"
        ),
        "sandbox_benchmark_run_metadata": _join(
            output_root, "silver/sandbox_benchmark_run_metadata.parquet"
        ),
    }
    write_parquet_rows(silver_refs["sandbox_hourly_prices"], price_rows)
    write_parquet_rows(silver_refs["sandbox_benchmark_batches"], batch_rows)
    write_parquet_rows(
        silver_refs["sandbox_benchmark_replicates"],
        replicate_rows,
    )
    write_parquet_rows(silver_refs["sandbox_benchmark_phases"], phase_rows)
    write_parquet_rows(
        silver_refs["sandbox_benchmark_run_metadata"],
        run_metadata,
    )

    hourly_gold = _canonicalize_numeric_rows(
        query_tables(
            tables={"sandbox_hourly_prices": silver_refs["sandbox_hourly_prices"]},
            sql="""
select *
from sandbox_hourly_prices
order by series_order, observed_date, point_order
""",
        )
    )
    fixed_rate = _canonicalize_numeric_rows(
        query_tables(
            tables={"sandbox_hourly_prices": silver_refs["sandbox_hourly_prices"]},
            sql=FIXED_RATE_SQL,
        )
    )
    price_events = _canonicalize_numeric_rows(
        query_tables(
            tables={"sandbox_hourly_prices": silver_refs["sandbox_hourly_prices"]},
            sql=PRICE_EVENTS_SQL,
        )
    )
    current_rates = _canonicalize_numeric_rows(
        query_tables(
            tables={"sandbox_hourly_prices": silver_refs["sandbox_hourly_prices"]},
            sql=CURRENT_RATES_SQL,
        )
    )
    workload_batches = _canonicalize_numeric_rows(
        query_tables(
            tables={
                "sandbox_benchmark_batches": silver_refs[
                    "sandbox_benchmark_batches"
                ]
            },
            sql=WORKLOAD_BATCH_SQL,
        )
    )
    latest_replicates = _canonicalize_numeric_rows(
        query_tables(
            tables={
                "sandbox_benchmark_replicates": silver_refs[
                    "sandbox_benchmark_replicates"
                ]
            },
            sql=WORKLOAD_LATEST_REPLICATES_SQL,
        )
    )
    latest_phases = _canonicalize_numeric_rows(
        query_tables(
            tables={
                "sandbox_benchmark_phases": silver_refs[
                    "sandbox_benchmark_phases"
                ]
            },
            sql=WORKLOAD_LATEST_PHASES_SQL,
        )
    )
    latest_replicates_ref = _join(
        output_root,
        "gold/sandbox_workload_latest_replicates.parquet",
    )
    latest_phases_ref = _join(
        output_root,
        "gold/sandbox_workload_latest_phases.parquet",
    )
    write_parquet_rows(latest_replicates_ref, latest_replicates)
    write_parquet_rows(latest_phases_ref, latest_phases)
    workload_summary = _canonicalize_numeric_rows(
        query_tables(
            tables={
                "sandbox_workload_latest_replicates": latest_replicates_ref
            },
            sql=WORKLOAD_SUMMARY_SQL,
        )
    )
    phase_summary = _canonicalize_numeric_rows(
        query_tables(
            tables={"sandbox_workload_latest_phases": latest_phases_ref},
            sql=WORKLOAD_PHASE_SUMMARY_SQL,
        )
    )

    gpu_rows, gpu_manifest = _load_gpu_history(gpu_history_ref)
    combined: list[dict[str, Any]] = []
    gpu_daily_coverage: list[dict[str, Any]] = []
    gpu_eligible_history: list[dict[str, Any]] = []
    gpu_silver_ref: str | None = None
    if gpu_rows:
        gpu_silver_ref = _join(output_root, "silver/gpu_benchmark_history.parquet")
        write_parquet_rows(gpu_silver_ref, gpu_rows)
        fixed_rate_ref = _join(output_root, "gold/sandbox_fixed_rate.parquet")
        gpu_daily_ref = _join(
            output_root, "gold/gpu_h100_daily_coverage.parquet"
        )
        gpu_eligible_ref = _join(
            output_root, "gold/gpu_h100_eligible_history.parquet"
        )
        write_parquet_rows(fixed_rate_ref, fixed_rate)
        gpu_daily_coverage = _canonicalize_numeric_rows(
            query_tables(
                tables={"gpu_benchmark_history": gpu_silver_ref},
                sql=GPU_DAILY_COVERAGE_SQL,
            )
        )
        write_parquet_rows(gpu_daily_ref, gpu_daily_coverage)
        gpu_eligible_history = _canonicalize_numeric_rows(
            query_tables(
                tables={"gpu_benchmark_history": gpu_silver_ref},
                sql=GPU_ELIGIBLE_HISTORY_SQL,
            )
        )
        write_parquet_rows(gpu_eligible_ref, gpu_eligible_history)
        combined = _canonicalize_numeric_rows(
            query_tables(
                tables={
                    "gpu_h100_eligible_history": gpu_eligible_ref,
                    "sandbox_fixed_rate": fixed_rate_ref,
                },
                sql=COMBINED_COMMON_START_SQL,
            )
        )

    table_refs = {
        "sandbox_hourly_price_series": _join(
            output_root, "gold/sandbox_hourly_price_series.parquet"
        ),
        "sandbox_price_events": _join(
            output_root, "gold/sandbox_price_events.parquet"
        ),
        "sandbox_current_rates": _join(
            output_root, "gold/sandbox_current_rates.parquet"
        ),
        "sandbox_fixed_rate": _join(
            output_root, "gold/sandbox_fixed_rate.parquet"
        ),
        "sandbox_workload_batch_history": _join(
            output_root, "gold/sandbox_workload_batch_history.parquet"
        ),
        "sandbox_workload_latest_replicates": latest_replicates_ref,
        "sandbox_workload_latest_phases": latest_phases_ref,
        "sandbox_workload_phase_summary": _join(
            output_root, "gold/sandbox_workload_phase_summary.parquet"
        ),
        "sandbox_workload_service_summary": _join(
            output_root, "gold/sandbox_workload_service_summary.parquet"
        ),
        "gpu_h100_daily_coverage": _join(
            output_root, "gold/gpu_h100_daily_coverage.parquet"
        ),
        "gpu_h100_eligible_history": _join(
            output_root, "gold/gpu_h100_eligible_history.parquet"
        ),
        "sandbox_gpu_cpu_common_start": _join(
            output_root, "gold/sandbox_gpu_cpu_common_start.parquet"
        ),
    }
    write_parquet_rows(table_refs["sandbox_hourly_price_series"], hourly_gold)
    write_parquet_rows(table_refs["sandbox_price_events"], price_events)
    write_parquet_rows(table_refs["sandbox_current_rates"], current_rates)
    write_parquet_rows(table_refs["sandbox_fixed_rate"], fixed_rate)
    write_parquet_rows(
        table_refs["sandbox_workload_batch_history"],
        workload_batches,
    )
    write_parquet_rows(
        table_refs["sandbox_workload_phase_summary"],
        phase_summary,
    )
    write_parquet_rows(
        table_refs["sandbox_workload_service_summary"],
        workload_summary,
    )
    write_parquet_rows(
        table_refs["gpu_h100_daily_coverage"], gpu_daily_coverage
    )
    write_parquet_rows(
        table_refs["gpu_h100_eligible_history"], gpu_eligible_history
    )
    write_parquet_rows(
        table_refs["sandbox_gpu_cpu_common_start"], combined
    )

    query_hashes = {
        "fixed_rate": _sha256_text(FIXED_RATE_SQL),
        "price_events": _sha256_text(PRICE_EVENTS_SQL),
        "current_rates": _sha256_text(CURRENT_RATES_SQL),
        "workload_batches": _sha256_text(WORKLOAD_BATCH_SQL),
        "workload_replicates": _sha256_text(
            WORKLOAD_LATEST_REPLICATES_SQL
        ),
        "workload_phases": _sha256_text(WORKLOAD_LATEST_PHASES_SQL),
        "workload_phase_summary": _sha256_text(
            WORKLOAD_PHASE_SUMMARY_SQL
        ),
        "workload_summary": _sha256_text(WORKLOAD_SUMMARY_SQL),
        "gpu_daily_coverage": _sha256_text(GPU_DAILY_COVERAGE_SQL),
        "gpu_eligible_history": _sha256_text(GPU_ELIGIBLE_HISTORY_SQL),
        "combined": _sha256_text(COMBINED_COMMON_START_SQL),
    }
    input_hash = _content_hash(
        {
            "prices": prices_payload,
            "benchmarks": benchmarks_payload,
            "source_manifest": source_manifest,
            "gpu_rows": gpu_rows,
            "gpu_source_manifest": _public_gpu_source_manifest(gpu_manifest),
            "target_shape": TARGET_SHAPE,
            "fixed_rate_cohort": FIXED_COHORT,
            "sandbox_rate_methodology": SANDBOX_RATE_METHODOLOGY,
            "gpu_comparison_min_providers": GPU_COMPARISON_MIN_PROVIDERS,
            "numeric_decimal_places": NUMERIC_DECIMAL_PLACES,
            "query_hashes": query_hashes,
        }
    )
    build_id = f"sandbox-cost-{input_hash[:16]}"
    built_at = _latest_timestamp(
        prices_payload.get("retrieved_at"),
        benchmarks_payload.get("retrieved_at"),
        gpu_manifest.get("dashboard_exported_at"),
        gpu_manifest.get("observed_at"),
    )
    row_counts = {
        "sandbox_hourly_price_series": len(hourly_gold),
        "sandbox_price_events": len(price_events),
        "sandbox_current_rates": len(current_rates),
        "sandbox_fixed_rate": len(fixed_rate),
        "sandbox_workload_batch_history": len(workload_batches),
        "sandbox_workload_latest_replicates": len(latest_replicates),
        "sandbox_workload_latest_phases": len(latest_phases),
        "sandbox_workload_phase_summary": len(phase_summary),
        "sandbox_workload_service_summary": len(workload_summary),
        "gpu_h100_daily_coverage": len(gpu_daily_coverage),
        "gpu_h100_eligible_history": len(gpu_eligible_history),
        "sandbox_gpu_cpu_common_start": len(combined),
    }
    manifest = {
        "manifest_version": "sandbox_cost_gold_v3",
        "build_id": build_id,
        "built_at": built_at,
        "input_hash": input_hash,
        "source_repository": source_manifest["source_repository"],
        "source_commit": source_manifest["source_commit"],
        "target_shape": TARGET_SHAPE,
        "source_reviewed_at": prices_payload.get("retrieved_at"),
        "benchmark_retrieved_at": benchmarks_payload.get("retrieved_at"),
        "fixed_rate_cohort": FIXED_COHORT,
        "sandbox_rate_methodology": SANDBOX_RATE_METHODOLOGY,
        "gpu_comparison_min_providers": GPU_COMPARISON_MIN_PROVIDERS,
        "numeric_decimal_places": NUMERIC_DECIMAL_PLACES,
        "query_ids": {
            "fixed_rate": FIXED_RATE_QUERY_ID,
            "price_events": PRICE_EVENTS_QUERY_ID,
            "current_rates": CURRENT_RATES_QUERY_ID,
            "workload_batches": WORKLOAD_BATCH_QUERY_ID,
            "workload_replicates": WORKLOAD_REPLICATE_QUERY_ID,
            "workload_phases": WORKLOAD_PHASE_QUERY_ID,
            "workload_phase_summary": WORKLOAD_PHASE_SUMMARY_QUERY_ID,
            "workload_summary": WORKLOAD_SUMMARY_QUERY_ID,
            "gpu_daily_coverage": GPU_DAILY_QUERY_ID,
            "gpu_eligible_history": GPU_ELIGIBLE_QUERY_ID,
            "combined": COMBINED_QUERY_ID,
        },
        "query_hashes": query_hashes,
        "bronze_refs": bronze_refs,
        "silver_refs": {
            **silver_refs,
            **({"gpu_benchmark_history": gpu_silver_ref} if gpu_silver_ref else {}),
        },
        "table_refs": table_refs,
        "row_counts": row_counts,
        "evidence_summary": summary,
        "gpu_source_manifest": gpu_manifest or None,
    }
    manifest_ref = _join(output_root, "gold/manifest.json")
    write_json(manifest_ref, manifest)

    public_ref = None
    if dashboard_output_root:
        public_ref = _join(dashboard_output_root, "sandbox-cost.json")
        write_json(
            public_ref,
            _public_payload(
                manifest=manifest,
                hourly_rows=hourly_gold,
                fixed_rate=fixed_rate,
                price_events=price_events,
                current_rates=current_rates,
                workload_batches=workload_batches,
                latest_replicates=latest_replicates,
                latest_phases=latest_phases,
                phase_summary=phase_summary,
                workload_summary=workload_summary,
                run_metadata=run_metadata,
                gpu_daily_coverage=gpu_daily_coverage,
                combined=combined,
            ),
        )

    return SandboxCostBuild(
        build_id=build_id,
        output_root=output_root,
        manifest_ref=manifest_ref,
        public_ref=public_ref,
        table_refs=table_refs,
        row_counts=row_counts,
    )


def query_sandbox_gold(
    *,
    output_root: str,
    query_id: str,
    limit: int | None = None,
) -> dict[str, Any]:
    """Run an allowlisted DataFusion query over maintained sandbox gold tables."""
    if query_id not in GOLD_QUERIES:
        choices = ", ".join(sorted(GOLD_QUERIES))
        raise ValueError(f"Unknown sandbox query {query_id!r}; choose one of: {choices}")
    manifest = read_json(_join(output_root, "gold/manifest.json"))
    sql = GOLD_QUERIES[query_id].strip()
    if limit is not None:
        if limit < 1:
            raise ValueError("limit must be positive")
        sql = f"{sql.rstrip(';')}\nlimit {int(limit)}"
    rows = query_tables(tables=manifest["table_refs"], sql=sql)
    return {
        "query_id": query_id,
        "engine": "datafusion",
        "build_id": manifest["build_id"],
        "rows": rows,
    }


def _validate_prices(raw_rows: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_rows, list) or not raw_rows:
        raise ValueError("Hourly-price evidence must contain a non-empty rows list")
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for position, raw in enumerate(raw_rows):
        row = _strict_row(raw, PRICE_FIELDS, f"hourly price row {position}")
        _parse_date(row["observed_date"], f"hourly price row {position}")
        key = (row["series_id"], row["observed_date"], row["source_url"])
        if key in seen:
            raise ValueError(f"Duplicate hourly-price observation: {key}")
        seen.add(key)
        if not str(row["source_url"]).startswith(("https://", "http://")):
            raise ValueError(f"Missing source URL for hourly-price observation {key}")
        expected = (
            Decimal(str(row["processor_quantity"]))
            * Decimal(str(row["processor_rate_usd_per_unit_hour"]))
            + Decimal(str(row["memory_gib"]))
            * Decimal(str(row["memory_rate_usd_per_gib_hour"]))
        )
        observed = Decimal(str(row["price_usd_per_hour"]))
        if abs(expected - observed) > Decimal("0.000001"):
            raise ValueError(
                f"Bad hourly-price formula for {row['series_id']} on "
                f"{row['observed_date']}: expected {expected}, found {observed}"
            )
        try:
            metering = RATE_METERING[str(row["series_id"])]
        except KeyError as error:
            raise ValueError(
                f"Missing rate-metering semantics for {row['series_id']}"
            ) from error
        rows.append({**row, **metering})
    return rows


def _validate_batches(
    raw_rows: Any,
    prices: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(raw_rows, list) or not raw_rows:
        raise ValueError("Benchmark evidence must contain non-empty batch_rows")
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    for position, raw in enumerate(raw_rows):
        row = _strict_row(raw, BATCH_FIELDS, f"benchmark batch {position}")
        _parse_date(row["observed_date"], f"benchmark batch {position}")
        _parse_timestamp(row["generated_at"], f"benchmark batch {position}")
        key = (
            row["series_id"],
            row["generated_at"],
            row["benchmark_run_id"],
        )
        if key in seen:
            raise ValueError(f"Duplicate benchmark batch: {key}")
        seen.add(key)
        _validate_workload_cost_row(row, prices, key)
        if row["observation_level"] != "provider_batch_summary":
            raise ValueError(f"Unexpected batch observation level for {key}")
        if row["runtime_basis"] != "sum_of_published_task_means":
            raise ValueError(f"Unexpected batch runtime basis for {key}")
        if int(row["replicate_count"]) < 1:
            raise ValueError(f"Invalid replicate count for {key}")
        if bool(row["replicate_data_available"]) and int(row["replicate_count"]) < 2:
            raise ValueError(f"Indexed replicate batch is too small for {key}")
        rows.append(row)
    return rows


def _validate_replicates(
    raw_rows: Any,
    prices: list[dict[str, Any]],
    batches: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(raw_rows, list) or not raw_rows:
        raise ValueError("Benchmark evidence must contain non-empty replicate_rows")
    batch_keys = {
        (row["series_id"], row["benchmark_run_id"]): row for row in batches
    }
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int]] = set()
    for position, raw in enumerate(raw_rows):
        row = _strict_row(raw, REPLICATE_FIELDS, f"benchmark replicate {position}")
        _parse_date(row["observed_date"], f"benchmark replicate {position}")
        _parse_timestamp(row["generated_at"], f"benchmark replicate {position}")
        key = (
            row["series_id"],
            row["benchmark_run_id"],
            int(row["replicate_index"]),
        )
        if key in seen:
            raise ValueError(f"Duplicate benchmark replicate: {key}")
        seen.add(key)
        _validate_workload_cost_row(row, prices, key)
        if row["observation_level"] != "aligned_job_replicate":
            raise ValueError(f"Unexpected replicate observation level for {key}")
        if (
            row["runtime_basis"]
            != "sum_of_ten_task_samples_with_same_replicate_index"
        ):
            raise ValueError(f"Unexpected replicate runtime basis for {key}")
        if int(row["task_count"]) != 10:
            raise ValueError(f"Expected ten phases for replicate {key}")
        batch = batch_keys.get((row["series_id"], row["benchmark_run_id"]))
        if batch is None:
            raise ValueError(f"Replicate has no retained batch: {key}")
        for field in (
            "methodology_id",
            "source_run_sha",
            "task_signature",
            "workload_app_version",
        ):
            if row[field] != batch[field]:
                raise ValueError(f"Replicate {key} disagrees with its batch on {field}")
        rows.append(row)

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(
            (row["series_id"], row["benchmark_run_id"]),
            [],
        ).append(row)
    for key, batch in batch_keys.items():
        if not batch["replicate_data_available"]:
            continue
        group = grouped.get(key, [])
        if len(group) != int(batch["replicate_count"]):
            raise ValueError(
                f"Replicate count does not match batch {key}: "
                f"{len(group)} != {batch['replicate_count']}"
            )
        mean_runtime = sum(float(row["runtime_seconds"]) for row in group) / len(
            group
        )
        if abs(mean_runtime - float(batch["runtime_seconds"])) > 0.000001:
            raise ValueError(f"Replicate mean does not reproduce batch runtime {key}")
    return rows


def _validate_phases(
    raw_rows: Any,
    replicates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(raw_rows, list) or not raw_rows:
        raise ValueError("Benchmark evidence must contain non-empty phase_rows")
    replicate_keys = {
        (
            row["series_id"],
            row["benchmark_run_id"],
            int(row["replicate_index"]),
        ): row
        for row in replicates
    }
    grouped: dict[tuple[str, str, int], list[dict[str, Any]]] = {}
    seen: set[tuple[str, str, int, str]] = set()
    rows: list[dict[str, Any]] = []
    for position, raw in enumerate(raw_rows):
        row = _strict_row(raw, PHASE_FIELDS, f"benchmark phase {position}")
        key = (
            row["series_id"],
            row["benchmark_run_id"],
            int(row["replicate_index"]),
            row["task_id"],
        )
        if key in seen:
            raise ValueError(f"Duplicate benchmark phase: {key}")
        seen.add(key)
        replicate_key = key[:3]
        replicate = replicate_keys.get(replicate_key)
        if replicate is None:
            raise ValueError(f"Phase has no retained replicate: {key}")
        if not 1 <= int(row["task_order"]) <= 10:
            raise ValueError(f"Invalid task order for phase {key}")
        if float(row["runtime_seconds"]) <= 0:
            raise ValueError(f"Invalid phase runtime for {key}")
        for field in (
            "methodology_id",
            "source_run_sha",
            "task_signature",
            "workload_app_version",
        ):
            if row[field] != replicate[field]:
                raise ValueError(f"Phase {key} disagrees with its replicate on {field}")
        grouped.setdefault(replicate_key, []).append(row)
        rows.append(row)
    for key, replicate in replicate_keys.items():
        phases = grouped.get(key, [])
        if len(phases) != 10 or {int(row["task_order"]) for row in phases} != set(
            range(1, 11)
        ):
            raise ValueError(f"Replicate {key} does not contain ten unique phases")
        total = sum(float(row["runtime_seconds"]) for row in phases)
        if abs(total - float(replicate["runtime_seconds"])) > 0.000001:
            raise ValueError(f"Phase total does not reproduce replicate runtime {key}")
    return rows


def _validate_run_metadata(
    raw_rows: Any,
    batches: list[dict[str, Any]],
    replicates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(raw_rows, list) or not raw_rows:
        raise ValueError("Benchmark evidence must contain non-empty run_metadata")
    batch_runs: dict[str, list[dict[str, Any]]] = {}
    replicate_runs = {row["benchmark_run_id"] for row in replicates}
    for row in batches:
        batch_runs.setdefault(row["benchmark_run_id"], []).append(row)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for position, raw in enumerate(raw_rows):
        row = _strict_row(raw, RUN_METADATA_FIELDS, f"run metadata {position}")
        run_id = row["benchmark_run_id"]
        if run_id in seen:
            raise ValueError(f"Duplicate run metadata: {run_id}")
        seen.add(run_id)
        _parse_timestamp(row["generated_at"], f"run metadata {position}")
        members = batch_runs.get(run_id)
        if not members:
            raise ValueError(f"Run metadata has no retained batch: {run_id}")
        if int(row["provider_result_count"]) != len(members):
            raise ValueError(f"Wrong provider count in run metadata {run_id}")
        if bool(row["replicate_indexed"]) != (run_id in replicate_runs):
            raise ValueError(f"Wrong replicate-indexed status in run metadata {run_id}")
        for member in members:
            for field in (
                "methodology_id",
                "source_run_sha",
                "task_signature",
                "workload_app_version",
            ):
                if row[field] != member[field]:
                    raise ValueError(
                        f"Run metadata {run_id} disagrees with batch on {field}"
                    )
        rows.append(row)
    if seen != set(batch_runs):
        raise ValueError("Run metadata does not cover every retained batch run")
    return rows


def _validate_workload_cost_row(
    row: dict[str, Any],
    prices: list[dict[str, Any]],
    key: tuple[Any, ...],
) -> None:
    shape = {
        "vcpus": int(row["vcpus"]),
        "memory_gib": int(row["memory_gib"]),
        "disk_gb": int(row["disk_gb"]),
    }
    if shape != TARGET_SHAPE:
        raise ValueError(
            f"Incompatible machine shape in {row['benchmark_run_id']}: {shape}"
        )
    if int(row["job_parts"]) != 10:
        raise ValueError(
            f"Expected ten job parts in {row['benchmark_run_id']} "
            f"for {row['series_id']}"
        )
    if row["price_scope"] != "processor_and_memory_only":
        raise ValueError(f"Unexpected price scope in benchmark result {key}")
    if row["cost_basis"] != "public_rate_card_unmetered":
        raise ValueError(f"Unexpected cost basis in benchmark result {key}")
    if row["lifecycle_included"] is not False:
        raise ValueError(f"Lifecycle must remain explicitly excluded for {key}")
    if float(row["runtime_seconds"]) <= 0:
        raise ValueError(f"Invalid workload runtime for {key}")
    if int(row["workload_gap_count"]) < 0:
        raise ValueError(f"Invalid workload gap count for {key}")
    if len(str(row["source_run_sha"])) != 40:
        raise ValueError(f"Missing source run SHA for {key}")
    if len(str(row["task_signature"])) != 64:
        raise ValueError(f"Missing task signature for {key}")
    if len(str(row["workload_app_version"])) != 40:
        raise ValueError(f"Missing workload version for {key}")
    if not str(row["methodology_id"]).startswith("starsling-better-auth-"):
        raise ValueError(f"Invalid methodology ID for {key}")
    if not str(row["benchmark_source_url"]).startswith(
        "https://github.com/starslingdev/hpc-sandbox-benchmarks/"
    ):
        raise ValueError(f"Missing benchmark source URL for {key}")
    if row["observed_vcpus"] is not None and abs(
        float(row["observed_vcpus"]) - TARGET_SHAPE["vcpus"]
    ) > 0.01:
        raise ValueError(f"Observed vCPU mismatch for {key}")
    if row["observed_memory_gib"] is not None and abs(
        float(row["observed_memory_gib"]) - TARGET_SHAPE["memory_gib"]
    ) > TARGET_SHAPE["memory_gib"] * 0.1:
        raise ValueError(f"Observed memory mismatch for {key}")

    expected_cost = (
        Decimal(str(row["runtime_seconds"]))
        * Decimal(str(row["hourly_price_usd"]))
        / Decimal("3600")
    )
    observed_cost = Decimal(str(row["estimated_cost_usd"]))
    if abs(expected_cost - observed_cost) > Decimal("0.000000001"):
        raise ValueError(
            f"Bad workload cost for {row['series_id']} on "
            f"{row['generated_at']}: expected {expected_cost}, "
            f"found {observed_cost}"
        )
    price_series = RUNTIME_PRICE_SERIES.get(row["series_id"])
    if price_series is None:
        raise ValueError(f"Unknown benchmark service {row['series_id']!r}")
    candidates = sorted(
        (
            price
            for price in prices
            if price["series_id"] == price_series
            and price["observed_date"] <= row["observed_date"]
        ),
        key=lambda price: price["observed_date"],
    )
    if not candidates:
        raise ValueError(
            f"No {price_series} price at or before {row['observed_date']}"
        )
    price = candidates[-1]
    if row["price_date"] != price["observed_date"]:
        raise ValueError(f"Wrong price date retained for benchmark result {key}")
    if row["price_source_url"] != price["source_url"]:
        raise ValueError(f"Wrong price source retained for benchmark result {key}")
    if abs(
        Decimal(str(row["hourly_price_usd"]))
        - Decimal(str(price["price_usd_per_hour"]))
    ) > Decimal("0.000001"):
        raise ValueError(f"Wrong hourly price retained for benchmark result {key}")


def _validate_source_manifest(
    manifest: dict[str, Any],
    benchmarks: list[dict[str, Any]],
) -> None:
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("Source manifest must contain files")
    paths: set[str] = set()
    for position, raw in enumerate(files):
        row = _strict_row(
            raw,
            {"path", "source_url", "sha256", "size_bytes"},
            f"source manifest row {position}",
        )
        if row["path"] in paths:
            raise ValueError(f"Duplicate source-manifest path: {row['path']}")
        paths.add(row["path"])
        if len(str(row["sha256"])) != 64:
            raise ValueError(f"Invalid SHA-256 for {row['path']}")
        if int(row["size_bytes"]) < 1:
            raise ValueError(f"Invalid source size for {row['path']}")
    for run_id in {row["benchmark_run_id"] for row in benchmarks}:
        expected_path = f"data/dataset/runs/{run_id}.json"
        if expected_path not in paths:
            raise ValueError(f"Source manifest does not retain run {run_id}")


def _public_payload(
    *,
    manifest: dict[str, Any],
    hourly_rows: list[dict[str, Any]],
    fixed_rate: list[dict[str, Any]],
    price_events: list[dict[str, Any]],
    current_rates: list[dict[str, Any]],
    workload_batches: list[dict[str, Any]],
    latest_replicates: list[dict[str, Any]],
    latest_phases: list[dict[str, Any]],
    phase_summary: list[dict[str, Any]],
    workload_summary: list[dict[str, Any]],
    run_metadata: list[dict[str, Any]],
    gpu_daily_coverage: list[dict[str, Any]],
    combined: list[dict[str, Any]],
) -> dict[str, Any]:
    source_rows: dict[str, dict[str, str]] = {}
    for row in hourly_rows:
        source_rows[row["source_url"]] = {
            "label": row["source_label"],
            "url": row["source_url"],
        }
    for row in workload_batches:
        source_rows[row["benchmark_source_url"]] = {
            "label": f"StarSling batch {row['benchmark_run_id']}",
            "url": row["benchmark_source_url"],
        }
    latest_run = max(run_metadata, key=lambda row: row["generated_at"])
    return {
        "manifest": {
            "manifest_version": manifest["manifest_version"],
            "build_id": manifest["build_id"],
            "built_at": manifest["built_at"],
            "target_shape": manifest["target_shape"],
            "source_reviewed_at": manifest["source_reviewed_at"],
            "benchmark_retrieved_at": manifest["benchmark_retrieved_at"],
            "fixed_rate_cohort": manifest["fixed_rate_cohort"],
            "sandbox_rate_methodology": manifest[
                "sandbox_rate_methodology"
            ],
            "gpu_comparison_min_providers": manifest[
                "gpu_comparison_min_providers"
            ],
            "numeric_decimal_places": manifest["numeric_decimal_places"],
            "query_ids": manifest["query_ids"],
            "row_counts": manifest["row_counts"],
            "gpu_source_manifest": _public_gpu_source_manifest(
                manifest["gpu_source_manifest"]
            ),
        },
        "hourly_price": {
            "title": (
                "Public hourly cost scenario for four processors and "
                "8 GiB of memory"
            ),
            "unit": "USD per hour",
            "rate_basis": "processor and memory rate card only",
            "comparison_scope": (
                "One hour at the audited four-processor, 8 GiB target. "
                "Actual-use meters assume those quantities are used for the "
                "full hour; reserved meters price the requested allocation. "
                "CPU model, isolation, burst policy, and delivered performance "
                "are not normalized by the rate series."
            ),
            "methodology_version": SANDBOX_RATE_METHODOLOGY,
            "rows": hourly_rows,
            "current_cross_section": current_rates,
            "fixed_cohort_rate": fixed_rate,
            # Keep the old field for one publication cycle while article caches expire.
            "fixed_membership_average": fixed_rate,
            "price_events": price_events,
        },
        "workload": {
            "title": (
                "One CI workload: measured phase time and estimated "
                "processor-and-memory cost"
            ),
            "benchmark": "StarSling HPC Sandbox Benchmark: Better Auth",
            "unit": "USD",
            "runtime_unit": "seconds",
            "cost_scope": "processor_and_memory_only",
            "cost_basis": "public_rate_card_unmetered",
            "claim_scope": "descriptive_observed_batch",
            "summary_statistics": [
                "all_individual_jobs",
                "median",
                "p25",
                "p75",
            ],
            "historical_comparability": "methodology_stratified",
            "runtime_definition": (
                "Guest wall time inside ten selected phase windows. Batch "
                "history sums published task means; latest job rows sum "
                "samples sharing one upstream replicate index."
            ),
            "replicate_runtime_basis": (
                "sum_of_ten_task_samples_with_same_replicate_index"
            ),
            "lifecycle_included": False,
            "excluded_time": [
                "sandbox startup",
                "sandbox teardown",
                "retries",
                "unmeasured warm-up and task preparation",
            ],
            "source_batch_count": len(
                {row["benchmark_run_id"] for row in workload_batches}
            ),
            "calendar_day_count": len(
                {row["observed_date"] for row in workload_batches}
            ),
            "methodology_generation_count": len(
                {row["methodology_id"] for row in run_metadata}
            ),
            "latest_run": latest_run,
            "latest_replicate_count": len(latest_replicates),
            "latest_source_replicate_slot_count": max(
                (
                    int(row["source_replicate_slot_count"])
                    for row in workload_summary
                ),
                default=0,
            ),
            "latest_incomplete_replicate_count": sum(
                int(row["incomplete_replicate_count"])
                for row in workload_summary
            ),
            "latest_phase_count": len(latest_phases),
            "batch_history": workload_batches,
            "latest_replicates": latest_replicates,
            "phase_summary": phase_summary,
            "service_summary": workload_summary,
        },
        "combined": {
            "title": "GPU and sandbox rates from a common starting point",
            "basis": (
                "Hourly H100 observed benchmark prints with at least "
                f"{GPU_COMPARISON_MIN_PROVIDERS} providers and the fixed-cohort "
                "sandbox median each equal 100 at the first eligible GPU print"
            ),
            "gpu_input": (
                "Eligible hourly H100 advertised provider-floor "
                "benchmark prints"
            ),
            "sandbox_input": (
                "As-of fixed eight-service median advertised sandbox rate"
            ),
            "coverage_gate": {
                "minimum_gpu_provider_count": GPU_COMPARISON_MIN_PROVIDERS,
                "excluded_history_is_retained": True,
            },
            "can_show": (
                "relative advertised-rate movement after broad H100 coverage "
                "begins, cross-sectional price dispersion, provider coverage, "
                "and the price ratio between one H100 GPU-hour and one "
                "standardized sandbox hour"
            ),
            "cannot_show": (
                "price-level equivalence, demand, transaction volume, or "
                "GPU utilization, causal effects, or total customer invoices"
            ),
            "coverage_history": gpu_daily_coverage,
            "rows": combined,
        },
        "sources": sorted(source_rows.values(), key=lambda row: row["label"]),
    }


def _public_gpu_source_manifest(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    allowed = (
        "manifest_version",
        "methodology_version",
        "run_id",
        "observed_at",
        "observed_date",
        "dashboard_exported_at",
        "provider_scope",
        "row_counts",
    )
    return {key: raw[key] for key in allowed if key in raw}


def _load_gpu_history(ref: str | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not ref:
        return [], {}
    if ref.partition("?")[0].lower().endswith(".parquet"):
        rows = query_tables(
            tables={"gpu_benchmark_history": ref},
            sql="""
select *
from gpu_benchmark_history
order by gold_observed_at, benchmark_family_id
""",
        )
        normalized = _normalize_gpu_history_rows(rows, ref)
        observed_at = max(
            (str(row["gold_observed_at"]) for row in normalized),
            default=None,
        )
        methodologies = sorted(
            {str(row["methodology_version"]) for row in normalized}
        )
        return normalized, {
            "manifest_version": "gpu_benchmark_history_parquet_v1",
            "methodology_version": (
                methodologies[0] if len(methodologies) == 1 else methodologies
            ),
            "observed_at": observed_at,
            "row_counts": {"benchmark_history": len(normalized)},
        }
    try:
        payload = read_json(ref)
    except FileNotFoundError:
        return [], {}
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise ValueError(f"GPU history at {ref} does not contain a rows list")
    return _normalize_gpu_history_rows(rows, ref), dict(
        payload.get("manifest") or {}
    )


def _normalize_gpu_history_rows(
    rows: list[Any],
    ref: str,
) -> list[dict[str, Any]]:
    required = {
        "gold_observed_at",
        "benchmark_family_id",
        "benchmark_usd_gpu_hr",
        "provider_count",
        "included_offer_count",
        "provider_floor_p25_usd_gpu_hr",
        "provider_floor_p75_usd_gpu_hr",
        "methodology_version",
        "benchmark_basis",
        "calculated_at",
    }
    normalized: list[dict[str, Any]] = []
    for position, raw in enumerate(rows):
        if not isinstance(raw, Mapping):
            raise ValueError(f"GPU history row {position} is not an object")
        missing = required - set(raw)
        if missing:
            raise ValueError(
                f"GPU history row {position} is missing: "
                f"{', '.join(sorted(missing))}"
            )
        _parse_timestamp(raw["gold_observed_at"], f"GPU history row {position}")
        if raw["benchmark_usd_gpu_hr"] is None:
            continue
        normalized.append(dict(raw))
    return normalized


def _read_local_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _require_schema(payload: dict[str, Any], expected: str, path: Path) -> None:
    observed = payload.get("schema_version")
    if observed != expected:
        raise ValueError(
            f"Schema drift in {path}: expected {expected!r}, found {observed!r}"
        )


def _strict_row(raw: Any, fields: set[str], label: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"{label} is not an object")
    observed = set(raw)
    missing = fields - observed
    extra = observed - fields
    if missing or extra:
        details = []
        if missing:
            details.append(f"missing {', '.join(sorted(missing))}")
        if extra:
            details.append(f"unexpected {', '.join(sorted(extra))}")
        raise ValueError(f"Schema drift in {label}: {'; '.join(details)}")
    return dict(raw)


def _parse_date(value: Any, label: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"Invalid date in {label}: {value!r}") from exc


def _parse_timestamp(value: Any, label: str) -> datetime:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Invalid timestamp in {label}: {value!r}") from exc


def _join(root: str, suffix: str) -> str:
    return f"{root.rstrip('/')}/{suffix.lstrip('/')}"


def _content_hash(*values: Any) -> str:
    payload = json.dumps(values, sort_keys=True, separators=(",", ":"), default=str)
    return _sha256_text(payload)


def _canonicalize_numeric_rows(
    rows: list[dict[str, Any]],
    *,
    decimal_places: int = NUMERIC_DECIMAL_PLACES,
) -> list[dict[str, Any]]:
    """Remove platform-level floating noise at the maintained Gold boundary."""
    return [
        {
            key: round(value, decimal_places) if isinstance(value, float) else value
            for key, value in row.items()
        }
        for row in rows
    ]


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _latest_timestamp(*values: Any) -> str:
    parsed = [
        _parse_timestamp(value, "build timestamp")
        for value in values
        if value
    ]
    if not parsed:
        return datetime.now(timezone.utc).isoformat()
    return max(parsed).isoformat()


def write_source_capture(ref: str, data: bytes) -> str:
    """Write immutable source bytes without altering their payload."""
    return write_bytes(ref, data, content_type="application/octet-stream")
