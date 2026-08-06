"""Build bronze, silver, and gold sandbox-cost products with DataFusion."""

from __future__ import annotations

from .operational_data import (
    load_operational_workload_benchmark,
    load_optional_json,
)
from .public_data import build_public_payload

from .evidence import (
    BENCHMARK_EVIDENCE,
    SOURCE_MANIFEST,
    TARGET_SHAPE,
    WORKLOAD_COST_INPUTS,
    _evidence_summary,
    _parse_timestamp,
    _read_local_json,
    _validate_prices,
    validate_evidence,
)

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from the_compute_bazaar.prices.datafusion import query_tables
from the_compute_bazaar.prices.leases import exclusive_lease
from the_compute_bazaar.prices.public_view_sandbox import sandbox_workload_view
from the_compute_bazaar.prices.publications import (
    publish_sandbox_workload_publication,
)
from the_compute_bazaar.prices.storage import (
    delete_uri,
    read_bytes,
    write_bytes,
    write_json,
    write_parquet_rows,
)
from the_compute_bazaar.sandbox_cost.sql_models import (
    sandbox_model_sql,
    sandbox_sql_models,
)

WORKLOAD_BATCH_QUERY_ID = "sandbox_workload_batch_history_v2"
WORKLOAD_MEASURED_HISTORY_QUERY_ID = "sandbox_workload_measured_history_v1"
WORKLOAD_REPLICATE_QUERY_ID = "sandbox_workload_latest_replicates_v2"
WORKLOAD_PHASE_QUERY_ID = "sandbox_workload_latest_phases_v1"
WORKLOAD_PHASE_SUMMARY_QUERY_ID = "sandbox_workload_phase_summary_v1"
WORKLOAD_SUMMARY_QUERY_ID = "sandbox_workload_service_summary_v2"
WORKLOAD_RUN_SUMMARY_QUERY_ID = "sandbox_workload_run_summary_v1"
WORKLOAD_SERVICE_COUNT = 6
NUMERIC_DECIMAL_PLACES = 12


WORKLOAD_BATCH_SQL = sandbox_model_sql("sandbox_workload_batch_history")

WORKLOAD_MEASURED_HISTORY_SQL = sandbox_model_sql("sandbox_workload_measured_history")

WORKLOAD_LATEST_REPLICATES_SQL = sandbox_model_sql("sandbox_workload_latest_replicates")

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
    workload_manifest = load_optional_json(workload_manifest_ref)
    if workload_manifest:
        (
            benchmarks_payload,
            source_manifest,
            batch_rows,
            replicate_rows,
            phase_rows,
            run_metadata,
        ) = load_operational_workload_benchmark(
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
        for retired_ref in (
            "sandbox-cost.json",
            "sandbox/rates.json",
            "sandbox/relative.json",
        ):
            delete_uri(_join(dashboard_output_root, retired_ref))
        public_payload = build_public_payload(
            manifest=manifest,
            workload_batches=workload_batches,
            workload_run_history=workload_run_history,
            workload_measured_history=workload_measured_history,
            latest_replicates=latest_replicates,
            latest_phases=latest_phases,
            phase_summary=phase_summary,
            workload_summary=workload_summary,
            run_metadata=run_metadata,
            expected_service_count=WORKLOAD_SERVICE_COUNT,
        )
        sandbox_card = sandbox_workload_view(public_payload)
        publish_sandbox_workload_publication(
            output_root=dashboard_output_root,
            workload_card=sandbox_card,
        )
        public_ref = _join(dashboard_output_root, "sandbox/workload.json")
        write_json(public_ref, sandbox_card)

    return SandboxCostBuild(
        build_id=build_id,
        output_root=output_root,
        manifest_ref=manifest_ref,
        public_ref=public_ref,
        table_refs=table_refs,
        row_counts=row_counts,
    )


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
