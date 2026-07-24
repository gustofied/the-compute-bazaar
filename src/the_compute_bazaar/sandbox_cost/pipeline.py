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
FIXED_AVERAGE_QUERY_ID = "sandbox_fixed_membership_average_v1"
SAME_JOB_QUERY_ID = "sandbox_same_job_cost_v1"
COMBINED_QUERY_ID = "sandbox_gpu_cpu_base100_v1"
NUMERIC_DECIMAL_PLACES = 12

RUNTIME_PRICE_SERIES = {
    "blaxel": "blaxel",
    "daytona-vm": "daytona",
    "e2b": "e2b",
    "modal-gvisor": "modal",
    "modal-vm": "modal",
    "novita": "novita",
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

BENCHMARK_FIELDS = {
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
    "job_parts",
    "benchmark_run_id",
    "benchmark_source_url",
    "price_date",
    "price_source_url",
    "note",
    "color",
}

FIXED_AVERAGE_SQL = f"""
with event_dates as (
  select distinct observed_date
  from sandbox_hourly_prices
  where observed_date >= '2026-01-01'
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
    prices.observed_date as source_price_date,
    prices.source_url,
    row_number() over (
      partition by dates.observed_date, prices.series_id
      order by prices.observed_date desc, prices.point_order desc
    ) as recency_rank
  from event_dates dates
  cross join members
  join sandbox_hourly_prices prices
    on prices.series_id = members.series_id
   and prices.observed_date <= dates.observed_date
),
current_members as (
  select *
  from ranked
  where recency_rank = 1
)
select
  observed_date,
  avg(price_usd_per_hour) as average_usd_per_hour,
  count(*) as member_count,
  min(price_usd_per_hour) as minimum_usd_per_hour,
  max(price_usd_per_hour) as maximum_usd_per_hour
from current_members
group by observed_date
having count(*) = 8
order by observed_date
"""

SAME_JOB_SQL = """
select
  series_order,
  point_order,
  series_id,
  series_label,
  observed_date,
  generated_at,
  runtime_seconds,
  hourly_price_usd,
  runtime_seconds / 3600.0 * hourly_price_usd as estimated_cost_usd,
  price_scope,
  vcpus,
  memory_gib,
  disk_gb,
  job_parts,
  benchmark_run_id,
  benchmark_source_url,
  price_date,
  price_source_url,
  note,
  color
from sandbox_benchmark_runs
order by series_order, generated_at, point_order
"""

COMBINED_BASE100_SQL = """
with compatible_gpu as (
  select
    gold_observed_at,
    cast(gold_observed_at as date) as observed_date,
    benchmark_family_id,
    benchmark_usd_gpu_hr,
    provider_count,
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
joined as (
  select
    gpu.gold_observed_at,
    gpu.observed_date,
    gpu.benchmark_usd_gpu_hr,
    gpu.provider_count,
    sandbox.observed_date as sandbox_price_date,
    sandbox.average_usd_per_hour,
    row_number() over (
      partition by gpu.gold_observed_at
      order by sandbox.observed_date desc
    ) as sandbox_recency_rank
  from compatible_gpu gpu
  join sandbox_fixed_average sandbox
    on cast(sandbox.observed_date as date) <= gpu.observed_date
  where gpu.duplicate_rank = 1
),
comparable as (
  select *
  from joined
  where sandbox_recency_rank = 1
),
based as (
  select
    *,
    first_value(benchmark_usd_gpu_hr) over (
      order by gold_observed_at
      rows between unbounded preceding and unbounded following
    ) as first_gpu_value,
    first_value(average_usd_per_hour) over (
      order by gold_observed_at
      rows between unbounded preceding and unbounded following
    ) as first_sandbox_value
  from comparable
)
select
  gold_observed_at,
  observed_date,
  benchmark_usd_gpu_hr,
  provider_count,
  sandbox_price_date,
  average_usd_per_hour as sandbox_average_usd_per_hour,
  benchmark_usd_gpu_hr / first_gpu_value * 100.0 as gpu_base_100,
  average_usd_per_hour / first_sandbox_value * 100.0 as sandbox_base_100
from based
order by gold_observed_at
"""

GOLD_QUERIES = {
    "hourly-prices": """
select *
from sandbox_hourly_price_series
order by series_order, observed_date, point_order
""",
    "fixed-average": """
select *
from sandbox_fixed_average
order by observed_date
""",
    "same-job-cost": """
select *
from sandbox_same_job_cost
order by series_order, generated_at, point_order
""",
    "combined-base100": """
select *
from sandbox_combined_base100
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
        "sandbox_benchmark_observation_v1",
        benchmark_path,
    )
    _require_schema(
        source_manifest,
        "sandbox_source_manifest_v1",
        source_manifest_path,
    )

    prices = _validate_prices(prices_payload.get("rows"))
    benchmarks = _validate_benchmarks(benchmarks_payload.get("rows"), prices)
    _validate_source_manifest(source_manifest, benchmarks)

    return {
        "price_observation_count": len(prices),
        "price_service_count": len({row["series_id"] for row in prices}),
        "benchmark_result_count": len(benchmarks),
        "benchmark_service_count": len({row["series_id"] for row in benchmarks}),
        "benchmark_run_count": len({row["benchmark_run_id"] for row in benchmarks}),
        "benchmark_calendar_day_count": len(
            {row["observed_date"] for row in benchmarks}
        ),
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
    price_rows = list(prices_payload["rows"])
    benchmark_rows = list(benchmarks_payload["rows"])

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
        "sandbox_benchmark_runs": _join(
            output_root, "silver/sandbox_benchmark_runs.parquet"
        ),
    }
    write_parquet_rows(silver_refs["sandbox_hourly_prices"], price_rows)
    write_parquet_rows(silver_refs["sandbox_benchmark_runs"], benchmark_rows)

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
    fixed_average = _canonicalize_numeric_rows(
        query_tables(
            tables={"sandbox_hourly_prices": silver_refs["sandbox_hourly_prices"]},
            sql=FIXED_AVERAGE_SQL,
        )
    )
    same_job = _canonicalize_numeric_rows(
        query_tables(
            tables={"sandbox_benchmark_runs": silver_refs["sandbox_benchmark_runs"]},
            sql=SAME_JOB_SQL,
        )
    )

    gpu_rows, gpu_manifest = _load_gpu_history(gpu_history_ref)
    combined: list[dict[str, Any]] = []
    gpu_silver_ref: str | None = None
    if gpu_rows:
        gpu_silver_ref = _join(output_root, "silver/gpu_benchmark_history.parquet")
        write_parquet_rows(gpu_silver_ref, gpu_rows)
        fixed_average_ref = _join(
            output_root, "gold/sandbox_fixed_average.parquet"
        )
        write_parquet_rows(fixed_average_ref, fixed_average)
        combined = _canonicalize_numeric_rows(
            query_tables(
                tables={
                    "gpu_benchmark_history": gpu_silver_ref,
                    "sandbox_fixed_average": fixed_average_ref,
                },
                sql=COMBINED_BASE100_SQL,
            )
        )

    table_refs = {
        "sandbox_hourly_price_series": _join(
            output_root, "gold/sandbox_hourly_price_series.parquet"
        ),
        "sandbox_fixed_average": _join(
            output_root, "gold/sandbox_fixed_average.parquet"
        ),
        "sandbox_same_job_cost": _join(
            output_root, "gold/sandbox_same_job_cost.parquet"
        ),
        "sandbox_combined_base100": _join(
            output_root, "gold/sandbox_combined_base100.parquet"
        ),
    }
    write_parquet_rows(table_refs["sandbox_hourly_price_series"], hourly_gold)
    write_parquet_rows(table_refs["sandbox_fixed_average"], fixed_average)
    write_parquet_rows(table_refs["sandbox_same_job_cost"], same_job)
    write_parquet_rows(table_refs["sandbox_combined_base100"], combined)

    query_hashes = {
        "fixed_average": _sha256_text(FIXED_AVERAGE_SQL),
        "same_job_cost": _sha256_text(SAME_JOB_SQL),
        "combined": _sha256_text(COMBINED_BASE100_SQL),
    }
    input_hash = _content_hash(
        {
            "prices": prices_payload,
            "benchmarks": benchmarks_payload,
            "source_manifest": source_manifest,
            "gpu_rows": gpu_rows,
            "gpu_source_manifest": _public_gpu_source_manifest(gpu_manifest),
            "target_shape": TARGET_SHAPE,
            "fixed_average_cohort": FIXED_COHORT,
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
        "sandbox_fixed_average": len(fixed_average),
        "sandbox_same_job_cost": len(same_job),
        "sandbox_combined_base100": len(combined),
    }
    manifest = {
        "manifest_version": "sandbox_cost_gold_v1",
        "build_id": build_id,
        "built_at": built_at,
        "input_hash": input_hash,
        "source_repository": source_manifest["source_repository"],
        "source_commit": source_manifest["source_commit"],
        "target_shape": TARGET_SHAPE,
        "fixed_average_cohort": FIXED_COHORT,
        "numeric_decimal_places": NUMERIC_DECIMAL_PLACES,
        "query_ids": {
            "fixed_average": FIXED_AVERAGE_QUERY_ID,
            "same_job_cost": SAME_JOB_QUERY_ID,
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
                fixed_average=fixed_average,
                same_job=same_job,
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
        rows.append(row)
    return rows


def _validate_benchmarks(
    raw_rows: Any,
    prices: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(raw_rows, list) or not raw_rows:
        raise ValueError("Benchmark evidence must contain a non-empty rows list")
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    by_price_series: dict[str, list[dict[str, Any]]] = {}
    for price in prices:
        by_price_series.setdefault(price["series_id"], []).append(price)
    for series_rows in by_price_series.values():
        series_rows.sort(key=lambda row: row["observed_date"])

    for position, raw in enumerate(raw_rows):
        row = _strict_row(raw, BENCHMARK_FIELDS, f"benchmark row {position}")
        _parse_date(row["observed_date"], f"benchmark row {position}")
        _parse_timestamp(row["generated_at"], f"benchmark row {position}")
        key = (
            row["series_id"],
            row["generated_at"],
            row["benchmark_run_id"],
        )
        if key in seen:
            raise ValueError(f"Duplicate benchmark result: {key}")
        seen.add(key)
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
        if not str(row["benchmark_source_url"]).startswith(
            "https://github.com/starslingdev/hpc-sandbox-benchmarks/"
        ):
            raise ValueError(f"Missing benchmark source URL for {key}")
        expected_cost = (
            Decimal(str(row["runtime_seconds"]))
            * Decimal(str(row["hourly_price_usd"]))
            / Decimal("3600")
        )
        observed_cost = Decimal(str(row["estimated_cost_usd"]))
        if abs(expected_cost - observed_cost) > Decimal("0.000000001"):
            raise ValueError(
                f"Bad same-job cost for {row['series_id']} on "
                f"{row['generated_at']}: expected {expected_cost}, "
                f"found {observed_cost}"
            )
        price_series = RUNTIME_PRICE_SERIES.get(row["series_id"])
        if price_series is None:
            raise ValueError(f"Unknown benchmark service {row['series_id']!r}")
        candidates = [
            price
            for price in by_price_series.get(price_series, [])
            if price["observed_date"] <= row["observed_date"]
        ]
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
        rows.append(row)
    return rows


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
    fixed_average: list[dict[str, Any]],
    same_job: list[dict[str, Any]],
    combined: list[dict[str, Any]],
) -> dict[str, Any]:
    source_rows: dict[str, dict[str, str]] = {}
    for row in hourly_rows:
        source_rows[row["source_url"]] = {
            "label": row["source_label"],
            "url": row["source_url"],
        }
    for row in same_job:
        source_rows[row["benchmark_source_url"]] = {
            "label": f"Benchmark run {row['benchmark_run_id']}",
            "url": row["benchmark_source_url"],
        }
    return {
        "manifest": {
            "manifest_version": manifest["manifest_version"],
            "build_id": manifest["build_id"],
            "built_at": manifest["built_at"],
            "target_shape": manifest["target_shape"],
            "fixed_average_cohort": manifest["fixed_average_cohort"],
            "numeric_decimal_places": manifest["numeric_decimal_places"],
            "query_ids": manifest["query_ids"],
            "row_counts": manifest["row_counts"],
            "gpu_source_manifest": _public_gpu_source_manifest(
                manifest["gpu_source_manifest"]
            ),
        },
        "hourly_price": {
            "title": "Public hourly price for four processors and 8 GB of memory",
            "unit": "USD per hour",
            "rows": hourly_rows,
            "fixed_membership_average": fixed_average,
        },
        "same_job_cost": {
            "title": "Cost of the same software job",
            "benchmark": "StarSling HPC Sandbox Benchmark: Better Auth",
            "unit": "USD",
            "runtime_unit": "seconds",
            "comparable_run_count": len(
                {row["benchmark_run_id"] for row in same_job}
            ),
            "calendar_day_count": len({row["observed_date"] for row in same_job}),
            "rows": same_job,
        },
        "combined": {
            "title": "Observed compute costs, rebased",
            "basis": "Each series equals 100 at its first shared observation",
            "can_show": (
                "relative movement in the observed H100 benchmark and the "
                "fixed-membership sandbox hourly average"
            ),
            "cannot_show": (
                "price-level equivalence, demand, transaction volume, or "
                "total customer invoices"
            ),
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
    try:
        payload = read_json(ref)
    except FileNotFoundError:
        return [], {}
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise ValueError(f"GPU history at {ref} does not contain a rows list")
    required = {
        "gold_observed_at",
        "benchmark_family_id",
        "benchmark_usd_gpu_hr",
        "provider_count",
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
    return normalized, dict(payload.get("manifest") or {})


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
