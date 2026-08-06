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
from the_compute_bazaar.prices.public_views import (
    sandbox_workload_view,
)
from the_compute_bazaar.prices.publications import (
    publish_sandbox_workload_publication,
)
from the_compute_bazaar.prices.storage import (
    delete_uri,
    exclusive_lease,
    read_bytes,
    read_json,
    read_optional_json,
    read_parquet_rows,
    write_bytes,
    write_json,
    write_parquet_rows,
)
from the_compute_bazaar.sandbox_cost.sql_models import (
    sandbox_model_sql,
    sandbox_sql_models,
)

EVIDENCE_ROOT = Path(__file__).with_name("evidence")
WORKLOAD_COST_INPUTS = EVIDENCE_ROOT / "workload-cost-inputs.json"
BENCHMARK_EVIDENCE = EVIDENCE_ROOT / "benchmark-observations.json"
SOURCE_MANIFEST = EVIDENCE_ROOT / "source-manifest.json"
TARGET_SHAPE = {"vcpus": 4, "memory_gib": 8, "disk_gb": 40}
WORKLOAD_COST_COHORT = "workload-cost-input"
WORKLOAD_BATCH_QUERY_ID = "sandbox_workload_batch_history_v2"
WORKLOAD_MEASURED_HISTORY_QUERY_ID = "sandbox_workload_measured_history_v1"
WORKLOAD_REPLICATE_QUERY_ID = "sandbox_workload_latest_replicates_v2"
WORKLOAD_PHASE_QUERY_ID = "sandbox_workload_latest_phases_v1"
WORKLOAD_PHASE_SUMMARY_QUERY_ID = "sandbox_workload_phase_summary_v1"
WORKLOAD_SUMMARY_QUERY_ID = "sandbox_workload_service_summary_v2"
WORKLOAD_RUN_SUMMARY_QUERY_ID = "sandbox_workload_run_summary_v1"
WORKLOAD_SERVICE_COUNT = 6
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
    "workload_cost_eligible",
    "workload_cost_cohort",
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

WORKLOAD_BATCH_SQL = sandbox_model_sql("sandbox_workload_batch_history")

WORKLOAD_MEASURED_HISTORY_SQL = sandbox_model_sql(
    "sandbox_workload_measured_history"
)

WORKLOAD_LATEST_REPLICATES_SQL = sandbox_model_sql(
    "sandbox_workload_latest_replicates"
)

WORKLOAD_LATEST_PHASES_SQL = sandbox_model_sql("sandbox_workload_latest_phases")

WORKLOAD_PHASE_SUMMARY_SQL = sandbox_model_sql("sandbox_workload_phase_summary")

WORKLOAD_SUMMARY_SQL = sandbox_model_sql("sandbox_workload_service_summary")

WORKLOAD_RUN_SUMMARY_SQL = sandbox_model_sql(
    "sandbox_workload_run_history",
    fragments={"expected_service_count": str(WORKLOAD_SERVICE_COUNT)},
)

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
    price_path: Path = WORKLOAD_COST_INPUTS,
    benchmark_path: Path = BENCHMARK_EVIDENCE,
    source_manifest_path: Path = SOURCE_MANIFEST,
) -> dict[str, Any]:
    """Validate formulas, matching rules, uniqueness, shape, and source retention."""
    prices_payload = _read_local_json(price_path)
    benchmarks_payload = _read_local_json(benchmark_path)
    source_manifest = _read_local_json(source_manifest_path)
    _require_schema(
        prices_payload,
        "sandbox_workload_cost_input_v2",
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

    return _evidence_summary(
        prices=prices,
        batches=batches,
        replicates=replicates,
        phases=phases,
        run_metadata=run_metadata,
        source_manifest=source_manifest,
    )


def _evidence_summary(
    *,
    prices: list[dict[str, Any]],
    batches: list[dict[str, Any]],
    replicates: list[dict[str, Any]],
    phases: list[dict[str, Any]],
    run_metadata: list[dict[str, Any]],
    source_manifest: dict[str, Any],
) -> dict[str, Any]:
    return {
        "price_input_count": len(prices),
        "priced_service_count": len({row["series_id"] for row in prices}),
        "benchmark_batch_count": len(batches),
        "benchmark_replicate_count": len(replicates),
        "benchmark_phase_count": len(phases),
        "benchmark_service_count": len({row["series_id"] for row in batches}),
        "benchmark_run_count": len({row["benchmark_run_id"] for row in batches}),
        "benchmark_calendar_day_count": len({row["observed_date"] for row in batches}),
        "benchmark_methodology_count": len(
            {row["methodology_id"] for row in run_metadata}
        ),
        "latest_replicate_run_id": max(
            run_metadata,
            key=lambda row: row["generated_at"],
        )["benchmark_run_id"],
        "priced_services": sorted(
            {
                row["series_id"]
                for row in prices
                if row["workload_cost_cohort"] == WORKLOAD_COST_COHORT
            }
        ),
        "source_file_count": len(source_manifest["files"]),
    }


def build_sandbox_cost(
    *,
    output_root: str = "data/sandbox-cost",
    dashboard_output_root: str | None = None,
    workload_benchmark_manifest_ref: str | None = None,
    price_path: Path = WORKLOAD_COST_INPUTS,
    benchmark_path: Path = BENCHMARK_EVIDENCE,
    source_manifest_path: Path = SOURCE_MANIFEST,
) -> SandboxCostBuild:
    """Build deterministic bronze, silver, gold, and optional public JSON."""
    with exclusive_lease(_join(output_root, "_locks/sandbox-cost-build.json")):
        return _build_workload_cost_unlocked(
            output_root=output_root,
            dashboard_output_root=dashboard_output_root,
            workload_benchmark_manifest_ref=workload_benchmark_manifest_ref,
            price_path=price_path,
            benchmark_path=benchmark_path,
            source_manifest_path=source_manifest_path,
        )


def _build_workload_cost_unlocked(
    *,
    output_root: str,
    dashboard_output_root: str | None,
    workload_benchmark_manifest_ref: str | None,
    price_path: Path,
    benchmark_path: Path,
    source_manifest_path: Path,
) -> SandboxCostBuild:
    """Build the maintained StarSling workload-cost product."""
    summary = validate_evidence(
        price_path=price_path,
        benchmark_path=benchmark_path,
        source_manifest_path=source_manifest_path,
    )
    prices_payload = _read_local_json(price_path)
    benchmarks_payload = _read_local_json(benchmark_path)
    source_manifest = _read_local_json(source_manifest_path)
    price_rows = _validate_prices(prices_payload["rows"])

    workload_manifest_ref = workload_benchmark_manifest_ref or _join(
        output_root,
        "silver/_manifests/workload_benchmark/latest.json",
    )
    workload_manifest = _load_optional_json(workload_manifest_ref)
    if workload_manifest:
        (
            benchmarks_payload,
            source_manifest,
            batch_rows,
            replicate_rows,
            phase_rows,
            run_metadata,
        ) = _load_operational_workload_benchmark(
            manifest=workload_manifest,
            prices=price_rows,
            canonical_payload=benchmarks_payload,
        )
        summary = _evidence_summary(
            prices=price_rows,
            batches=batch_rows,
            replicates=replicate_rows,
            phases=phase_rows,
            run_metadata=run_metadata,
            source_manifest=source_manifest,
        )
    else:
        batch_rows = list(benchmarks_payload["batch_rows"])
        replicate_rows = list(benchmarks_payload["replicate_rows"])
        phase_rows = list(benchmarks_payload["phase_rows"])
        run_metadata = list(benchmarks_payload["run_metadata"])

    bronze_refs = {
        "workload_cost_inputs": _join(
            output_root,
            "bronze/workload-cost-inputs.json",
        ),
        "benchmark_evidence": _join(output_root, "bronze/benchmark-evidence.json"),
        "source_manifest": _join(output_root, "bronze/source-manifest.json"),
    }
    write_json(bronze_refs["workload_cost_inputs"], prices_payload)
    write_json(bronze_refs["benchmark_evidence"], benchmarks_payload)
    write_json(bronze_refs["source_manifest"], source_manifest)

    silver_refs = {
        "sandbox_benchmark_batches": _join(
            output_root,
            "silver/sandbox_benchmark_batches.parquet",
        ),
        "sandbox_benchmark_replicates": _join(
            output_root,
            "silver/sandbox_benchmark_replicates.parquet",
        ),
        "sandbox_benchmark_phases": _join(
            output_root,
            "silver/sandbox_benchmark_phases.parquet",
        ),
        "sandbox_benchmark_run_metadata": _join(
            output_root,
            "silver/sandbox_benchmark_run_metadata.parquet",
        ),
    }
    write_parquet_rows(silver_refs["sandbox_benchmark_batches"], batch_rows)
    write_parquet_rows(silver_refs["sandbox_benchmark_replicates"], replicate_rows)
    write_parquet_rows(silver_refs["sandbox_benchmark_phases"], phase_rows)
    write_parquet_rows(silver_refs["sandbox_benchmark_run_metadata"], run_metadata)

    workload_batches = _canonicalize_numeric_rows(
        query_tables(
            tables={
                "sandbox_benchmark_batches": silver_refs["sandbox_benchmark_batches"]
            },
            sql=WORKLOAD_BATCH_SQL,
        )
    )
    workload_run_history = _canonicalize_numeric_rows(
        query_tables(
            tables={
                "sandbox_benchmark_batches": silver_refs["sandbox_benchmark_batches"]
            },
            sql=WORKLOAD_RUN_SUMMARY_SQL,
        )
    )
    workload_measured_history = _canonicalize_numeric_rows(
        query_tables(
            tables={
                "sandbox_benchmark_batches": silver_refs["sandbox_benchmark_batches"]
            },
            sql=WORKLOAD_MEASURED_HISTORY_SQL,
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
                "sandbox_benchmark_phases": silver_refs["sandbox_benchmark_phases"]
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
            tables={"sandbox_workload_latest_replicates": latest_replicates_ref},
            sql=WORKLOAD_SUMMARY_SQL,
        )
    )
    phase_summary = _canonicalize_numeric_rows(
        query_tables(
            tables={"sandbox_workload_latest_phases": latest_phases_ref},
            sql=WORKLOAD_PHASE_SUMMARY_SQL,
        )
    )

    table_refs = {
        "sandbox_workload_batch_history": _join(
            output_root,
            "gold/sandbox_workload_batch_history.parquet",
        ),
        "sandbox_workload_run_history": _join(
            output_root,
            "gold/sandbox_workload_run_history.parquet",
        ),
        "sandbox_workload_measured_history": _join(
            output_root,
            "gold/sandbox_workload_measured_history.parquet",
        ),
        "sandbox_workload_latest_replicates": latest_replicates_ref,
        "sandbox_workload_latest_phases": latest_phases_ref,
        "sandbox_workload_phase_summary": _join(
            output_root,
            "gold/sandbox_workload_phase_summary.parquet",
        ),
        "sandbox_workload_service_summary": _join(
            output_root,
            "gold/sandbox_workload_service_summary.parquet",
        ),
    }
    write_parquet_rows(table_refs["sandbox_workload_batch_history"], workload_batches)
    write_parquet_rows(
        table_refs["sandbox_workload_run_history"],
        workload_run_history,
    )
    write_parquet_rows(
        table_refs["sandbox_workload_measured_history"],
        workload_measured_history,
    )
    write_parquet_rows(table_refs["sandbox_workload_phase_summary"], phase_summary)
    write_parquet_rows(
        table_refs["sandbox_workload_service_summary"],
        workload_summary,
    )

    query_hashes = {
        "workload_batches": _sha256_text(WORKLOAD_BATCH_SQL),
        "workload_run_history": _sha256_text(WORKLOAD_RUN_SUMMARY_SQL),
        "workload_measured_history": _sha256_text(WORKLOAD_MEASURED_HISTORY_SQL),
        "workload_replicates": _sha256_text(WORKLOAD_LATEST_REPLICATES_SQL),
        "workload_phases": _sha256_text(WORKLOAD_LATEST_PHASES_SQL),
        "workload_phase_summary": _sha256_text(WORKLOAD_PHASE_SUMMARY_SQL),
        "workload_summary": _sha256_text(WORKLOAD_SUMMARY_SQL),
    }
    input_hash = _content_hash(
        {
            "cost_inputs": prices_payload,
            "benchmarks": benchmarks_payload,
            "source_manifest": source_manifest,
            "target_shape": TARGET_SHAPE,
            "numeric_decimal_places": NUMERIC_DECIMAL_PLACES,
            "query_hashes": query_hashes,
        }
    )
    build_id = f"sandbox-cost-{input_hash[:16]}"
    built_at = _latest_timestamp(
        prices_payload.get("retrieved_at"),
        benchmarks_payload.get("retrieved_at"),
    )
    silver_refs = _promote_generation_refs(
        refs=silver_refs,
        output_root=output_root,
        layer="silver",
        build_id=build_id,
    )
    table_refs = _promote_generation_refs(
        refs=table_refs,
        output_root=output_root,
        layer="gold",
        build_id=build_id,
    )
    row_counts = {
        "sandbox_workload_batch_history": len(workload_batches),
        "sandbox_workload_run_history": len(workload_run_history),
        "sandbox_workload_measured_history": len(workload_measured_history),
        "sandbox_workload_latest_replicates": len(latest_replicates),
        "sandbox_workload_latest_phases": len(latest_phases),
        "sandbox_workload_phase_summary": len(phase_summary),
        "sandbox_workload_service_summary": len(workload_summary),
    }
    sql_models = sandbox_sql_models(table_refs)
    manifest_ref = _join(
        output_root,
        f"_manifests/sandbox_cost/date={built_at[:10]}/build_id={build_id}.json",
    )
    manifest = {
        "manifest_version": "sandbox_workload_cost_gold_v1",
        "manifest_ref": manifest_ref,
        "build_id": build_id,
        "built_at": built_at,
        "input_hash": input_hash,
        "source_repository": source_manifest["source_repository"],
        "source_commit": source_manifest["source_commit"],
        "target_shape": TARGET_SHAPE,
        "source_reviewed_at": prices_payload.get("retrieved_at"),
        "benchmark_retrieved_at": benchmarks_payload.get("retrieved_at"),
        "numeric_decimal_places": NUMERIC_DECIMAL_PLACES,
        "query_ids": {
            "workload_batches": WORKLOAD_BATCH_QUERY_ID,
            "workload_run_history": WORKLOAD_RUN_SUMMARY_QUERY_ID,
            "workload_measured_history": WORKLOAD_MEASURED_HISTORY_QUERY_ID,
            "workload_replicates": WORKLOAD_REPLICATE_QUERY_ID,
            "workload_phases": WORKLOAD_PHASE_QUERY_ID,
            "workload_phase_summary": WORKLOAD_PHASE_SUMMARY_QUERY_ID,
            "workload_summary": WORKLOAD_SUMMARY_QUERY_ID,
        },
        "query_hashes": query_hashes,
        "sql_models": sql_models,
        "bronze_refs": bronze_refs,
        "silver_refs": silver_refs,
        "table_refs": table_refs,
        "row_counts": row_counts,
        "evidence_summary": summary,
        "benchmark_credit": {
            "name": "StarSling HPC Sandbox Benchmark",
            "url": "https://github.com/starslingdev/hpc-sandbox-benchmarks",
        },
    }
    write_json(manifest_ref, manifest)
    write_json(_join(output_root, "_manifests/sandbox_cost/latest.json"), manifest)
    write_json(_join(output_root, "gold/manifest.json"), manifest)

    for retired_ref in (
        "bronze/hourly-price-evidence.json",
        "bronze/utilization-methodology.json",
        "silver/sandbox_hourly_prices.parquet",
        "silver/compute_utilization_metric_definitions.parquet",
        "gold/sandbox_hourly_price_series.parquet",
        "gold/sandbox_price_events.parquet",
        "gold/sandbox_current_rates.parquet",
        "gold/sandbox_fixed_rate.parquet",
        "gold/sandbox_gpu_cpu_common_start.parquet",
        "gold/gpu_vm_sandbox_common_start.parquet",
        "gold/compute_utilization_public_ladder.parquet",
        "gold/vm_sandbox_current_comparison.parquet",
    ):
        delete_uri(_join(output_root, retired_ref))

    public_ref = None
    if dashboard_output_root:
        for retired_ref in ("sandbox/rates.json", "sandbox/relative.json"):
            delete_uri(_join(dashboard_output_root, retired_ref))
        public_ref = _join(dashboard_output_root, "sandbox-cost.json")
        public_payload = _public_payload(
            manifest=manifest,
            workload_batches=workload_batches,
            workload_run_history=workload_run_history,
            workload_measured_history=workload_measured_history,
            latest_replicates=latest_replicates,
            latest_phases=latest_phases,
            phase_summary=phase_summary,
            workload_summary=workload_summary,
            run_metadata=run_metadata,
        )
        sandbox_card = sandbox_workload_view(public_payload)
        publication = publish_sandbox_workload_publication(
            output_root=dashboard_output_root,
            workload_card=sandbox_card,
        )
        public_payload["publications"] = {
            "manifest_ref": publication["manifest_ref"],
            "revision": publication["revision"],
            "publication_count": publication["publication_count"],
        }
        write_json(public_ref, public_payload)
        write_json(_join(dashboard_output_root, "sandbox/workload.json"), sandbox_card)

    return SandboxCostBuild(
        build_id=build_id,
        output_root=output_root,
        manifest_ref=manifest_ref,
        public_ref=public_ref,
        table_refs=table_refs,
        row_counts=row_counts,
    )


def read_latest_sandbox_manifest(output_root: str) -> dict[str, Any]:
    """Read the latest complete sandbox generation pointer."""
    latest = read_optional_json(
        _join(output_root, "_manifests/sandbox_cost/latest.json")
    )
    if latest:
        return latest
    return dict(read_json(_join(output_root, "gold/manifest.json")))


def check_public_payload_freshness(
    payload: Mapping[str, Any],
    *,
    now: datetime | str | None = None,
    max_age_hours: float = 2.5,
) -> dict[str, Any]:
    """Check the public workload-cost snapshot and its measured source run."""
    if max_age_hours <= 0:
        raise ValueError("max_age_hours must be positive")
    checked_at = (
        _parse_timestamp(now, "freshness check")
        if isinstance(now, str)
        else (now or datetime.now(timezone.utc))
    )
    if checked_at.tzinfo is None:
        checked_at = checked_at.replace(tzinfo=timezone.utc)
    checked_at = checked_at.astimezone(timezone.utc)

    manifest = payload.get("manifest")
    if not isinstance(manifest, Mapping):
        raise ValueError("Public snapshot has no manifest object")
    built_at = _as_utc(_parse_timestamp(manifest.get("built_at"), "public built_at"))
    workload = payload.get("workload")
    if not isinstance(workload, Mapping):
        raise ValueError("Public snapshot has no measured workload object")
    latest_run = workload.get("latest_run")
    if not isinstance(latest_run, Mapping):
        raise ValueError("Public snapshot has no latest measured workload run")
    measured_at = _as_utc(
        _parse_timestamp(latest_run.get("generated_at"), "workload generated_at")
    )

    snapshot_age_hours = (checked_at - built_at).total_seconds() / 3600
    problems: list[str] = []
    if snapshot_age_hours > max_age_hours:
        problems.append("public_snapshot_stale")
    if measured_at > checked_at:
        problems.append("measured_run_is_in_the_future")
    return {
        "status": "fail" if problems else "ok",
        "checked_at": checked_at.isoformat(),
        "max_age_hours": max_age_hours,
        "snapshot_built_at": built_at.isoformat(),
        "snapshot_age_hours": round(snapshot_age_hours, 3),
        "latest_measured_run_at": measured_at.isoformat(),
        "latest_measured_run_age_hours": round(
            (checked_at - measured_at).total_seconds() / 3600,
            3,
        ),
        "problems": problems,
    }


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


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
        expected = Decimal(str(row["processor_quantity"])) * Decimal(
            str(row["processor_rate_usd_per_unit_hour"])
        ) + Decimal(str(row["memory_gib"])) * Decimal(
            str(row["memory_rate_usd_per_gib_hour"])
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
    batch_keys = {(row["series_id"], row["benchmark_run_id"]): row for row in batches}
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
        if row["runtime_basis"] != "sum_of_ten_task_samples_with_same_replicate_index":
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
        mean_runtime = sum(float(row["runtime_seconds"]) for row in group) / len(group)
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
    if (
        row["observed_vcpus"] is not None
        and abs(float(row["observed_vcpus"]) - TARGET_SHAPE["vcpus"]) > 0.01
    ):
        raise ValueError(f"Observed vCPU mismatch for {key}")
    if (
        row["observed_memory_gib"] is not None
        and abs(float(row["observed_memory_gib"]) - TARGET_SHAPE["memory_gib"])
        > TARGET_SHAPE["memory_gib"] * 0.1
    ):
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
        raise ValueError(f"No {price_series} price at or before {row['observed_date']}")
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
    workload_batches: list[dict[str, Any]],
    workload_run_history: list[dict[str, Any]],
    workload_measured_history: list[dict[str, Any]],
    latest_replicates: list[dict[str, Any]],
    latest_phases: list[dict[str, Any]],
    phase_summary: list[dict[str, Any]],
    workload_summary: list[dict[str, Any]],
    run_metadata: list[dict[str, Any]],
) -> dict[str, Any]:
    source_rows: dict[str, dict[str, str]] = {}
    for row in workload_batches:
        source_rows[row["benchmark_source_url"]] = {
            "label": f"StarSling batch {row['benchmark_run_id']}",
            "url": row["benchmark_source_url"],
        }
    for row in latest_replicates:
        price_url = str(row.get("price_source_url") or "").strip()
        if price_url:
            source_rows[price_url] = {
                "label": f"{row['series_label']} cost input",
                "url": price_url,
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
            "numeric_decimal_places": manifest["numeric_decimal_places"],
            "row_counts": {
                key: value
                for key, value in manifest["row_counts"].items()
                if key.startswith("sandbox_workload_")
            },
        },
        "workload": {
            "title": ("Latest measured cost of one pinned software workload"),
            "benchmark": "StarSling HPC Sandbox Benchmark",
            "benchmark_url": ("https://github.com/starslingdev/hpc-sandbox-benchmarks"),
            "workload": "Better Auth ten-task developer workflow",
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
            "expected_service_count": WORKLOAD_SERVICE_COUNT,
            "complete_run_count": len(
                [row for row in workload_run_history if row["service_set_complete"]]
            ),
            "latest_run": latest_run,
            "latest_replicate_count": len(latest_replicates),
            "latest_source_replicate_slot_count": max(
                (int(row["source_replicate_slot_count"]) for row in workload_summary),
                default=0,
            ),
            "latest_incomplete_replicate_count": sum(
                int(row["incomplete_replicate_count"]) for row in workload_summary
            ),
            "latest_phase_count": len(latest_phases),
            "batch_history": workload_batches,
            "run_history": workload_run_history,
            "measured_history": workload_measured_history,
            "latest_replicates": latest_replicates,
            "phase_summary": phase_summary,
            "service_summary": workload_summary,
        },
        "sources": sorted(source_rows.values(), key=lambda row: row["label"]),
    }


def _load_optional_json(ref: str | None) -> dict[str, Any]:
    if not ref:
        return {}
    try:
        value = read_json(ref)
    except FileNotFoundError:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"Expected JSON object at {ref}")
    return dict(value)


def _load_operational_workload_benchmark(
    *,
    manifest: dict[str, Any],
    prices: list[dict[str, Any]],
    canonical_payload: dict[str, Any],
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    """Load and validate the latest trusted recurring workload generation."""
    if manifest.get("manifest_version") != "sandbox_workload_dataset_v1":
        raise ValueError(
            "Unsupported recurring workload manifest: "
            f"{manifest.get('manifest_version')!r}"
        )
    if manifest.get("target_shape") != TARGET_SHAPE:
        raise ValueError(
            "Recurring workload manifest has an incompatible machine shape"
        )
    expected_tables = {
        "sandbox_benchmark_batches",
        "sandbox_benchmark_replicates",
        "sandbox_benchmark_phases",
        "sandbox_benchmark_run_metadata",
    }
    table_refs = manifest.get("table_refs")
    if not isinstance(table_refs, dict) or set(table_refs) != expected_tables:
        raise ValueError(
            "Recurring workload manifest table refs drifted: expected "
            f"{sorted(expected_tables)}"
        )
    if not all(isinstance(ref, str) and ref for ref in table_refs.values()):
        raise ValueError("Recurring workload table refs must be non-empty strings")

    source_manifest_ref = manifest.get("source_manifest_ref")
    if not isinstance(source_manifest_ref, str) or not source_manifest_ref:
        raise ValueError("Recurring workload manifest has no source manifest ref")
    source_manifest = read_json(source_manifest_ref)
    if not isinstance(source_manifest, dict):
        raise ValueError("Recurring workload source manifest must be an object")
    for field in ("source_repository", "source_commit"):
        if source_manifest.get(field) != manifest.get(field):
            raise ValueError(
                f"Recurring workload {field} disagrees with its source manifest"
            )

    batches = _validate_batches(
        read_parquet_rows(str(table_refs["sandbox_benchmark_batches"])),
        prices,
    )
    replicates = _validate_replicates(
        read_parquet_rows(str(table_refs["sandbox_benchmark_replicates"])),
        prices,
        batches,
    )
    phases = _validate_phases(
        read_parquet_rows(str(table_refs["sandbox_benchmark_phases"])),
        replicates,
    )
    run_metadata = _validate_run_metadata(
        read_parquet_rows(str(table_refs["sandbox_benchmark_run_metadata"])),
        batches,
        replicates,
    )
    _validate_source_manifest(source_manifest, batches)

    canonical_keys = {
        (str(row["series_id"]), str(row["benchmark_run_id"]))
        for row in canonical_payload.get("batch_rows", [])
    }
    operational_keys = {
        (str(row["series_id"]), str(row["benchmark_run_id"])) for row in batches
    }
    missing = canonical_keys - operational_keys
    if missing:
        raise ValueError(
            "Recurring workload generation would drop reviewed history: "
            f"{sorted(missing)[:5]}"
        )

    payload = {
        **canonical_payload,
        "retrieved_at": manifest.get("dataset_observed_at"),
        "source_repository": manifest.get("source_repository"),
        "source_commit": manifest.get("source_commit"),
        "batch_rows": batches,
        "replicate_rows": replicates,
        "phase_rows": phases,
        "run_metadata": run_metadata,
    }
    return (
        payload,
        source_manifest,
        batches,
        replicates,
        phases,
        run_metadata,
    )


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


def _promote_generation_refs(
    *,
    refs: Mapping[str, str],
    output_root: str,
    layer: str,
    build_id: str,
) -> dict[str, str]:
    """Copy completed staging tables into an immutable, manifest-addressed build."""
    promoted: dict[str, str] = {}
    for table_name, source_ref in refs.items():
        destination = _join(
            output_root,
            f"{layer}/generations/build_id={build_id}/{table_name}.parquet",
        )
        write_bytes(
            destination,
            read_bytes(source_ref),
            content_type="application/octet-stream",
        )
        promoted[table_name] = destination
    return promoted


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
    parsed = [_parse_timestamp(value, "build timestamp") for value in values if value]
    if not parsed:
        return datetime.now(timezone.utc).isoformat()
    return max(parsed).isoformat()


def write_source_capture(ref: str, data: bytes) -> str:
    """Write immutable source bytes without altering their payload."""
    return write_bytes(ref, data, content_type="application/octet-stream")
