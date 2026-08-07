"""Publish immutable recurring StarSling observation generations."""

from __future__ import annotations

from .refresh_support import _merge_rows, _stable_rows

import hashlib
import json
from typing import Any

from the_compute_bazaar.contracts import (
    SANDBOX_SOURCE_CONTRACT,
    SANDBOX_WORKLOAD_DATASET_CONTRACT,
    SANDBOX_WORKLOAD_POLL_CONTRACT,
)

from .evidence import (
    BENCHMARK_EVIDENCE,
    TARGET_SHAPE,
    _read_local_json,
    _validate_batches,
    _validate_phases,
    _validate_replicates,
    _validate_run_metadata,
    _validate_source_manifest,
)
from the_compute_bazaar.prices.leases import exclusive_lease
from the_compute_bazaar.prices.storage import (
    read_optional_json,
    read_parquet_rows,
    write_json,
    write_parquet_rows,
)


def _publish_operational_benchmark(
    *,
    output_root: str,
    source_repository: str,
    source_commit: str,
    checked_at: str,
    refresh_id: str,
    source_manifest: dict[str, Any],
    source_manifest_ref: str,
    prices: list[dict[str, Any]],
    batch_rows: list[dict[str, Any]],
    replicate_rows: list[dict[str, Any]],
    phase_rows: list[dict[str, Any]],
    run_metadata: list[dict[str, Any]],
) -> dict[str, Any]:
    """Publish a trusted benchmark dataset generation for the weekly Gold build."""
    batches = _validate_batches(batch_rows, prices)
    replicates = _validate_replicates(replicate_rows, prices, batches)
    phases = _validate_phases(phase_rows, replicates)
    runs = _validate_run_metadata(run_metadata, batches, replicates)
    _validate_source_manifest(source_manifest, batches)

    stable_source_manifest = {
        "contract": SANDBOX_SOURCE_CONTRACT,
        "source_repository": source_repository,
        "source_commit": source_commit,
        "files": source_manifest["files"],
        "notes": source_manifest.get("notes", []),
    }
    content = {
        "source_manifest": stable_source_manifest,
        "target_shape": TARGET_SHAPE,
        "batch_rows": batches,
        "replicate_rows": replicates,
        "phase_rows": phases,
        "run_metadata": runs,
    }
    generation_hash = hashlib.sha256(
        json.dumps(
            content,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    generation_id = f"sandbox-workload-{generation_hash[:16]}"
    generation_prefix = (
        f"{output_root.rstrip('/')}/silver/workload_benchmark/"
        f"generations/generation_id={generation_id}"
    )
    table_refs = {
        "sandbox_benchmark_batches": f"{generation_prefix}/batch_history.parquet",
        "sandbox_benchmark_replicates": (
            f"{generation_prefix}/replicate_history.parquet"
        ),
        "sandbox_benchmark_phases": f"{generation_prefix}/phase_history.parquet",
        "sandbox_benchmark_run_metadata": (f"{generation_prefix}/run_metadata.parquet"),
    }
    dataset_source_manifest_ref = f"{generation_prefix}/source-manifest.json"
    dataset_manifest_ref = f"{generation_prefix}/manifest.json"
    latest_ref = (
        f"{output_root.rstrip('/')}/silver/_manifests/workload_benchmark/latest.json"
    )
    poll_ref = (
        f"{output_root.rstrip('/')}/silver/_manifests/workload_benchmark/"
        f"polls/date={checked_at[:10]}/refresh_id={refresh_id}.json"
    )
    latest_run = max(runs, key=lambda row: str(row["generated_at"]))
    dataset_manifest = {
        "contract": SANDBOX_WORKLOAD_DATASET_CONTRACT,
        "manifest_ref": dataset_manifest_ref,
        "generation_id": generation_id,
        "content_sha256": generation_hash,
        "source_repository": source_repository,
        "source_commit": source_commit,
        "dataset_observed_at": latest_run["generated_at"],
        "target_shape": TARGET_SHAPE,
        "source_manifest_ref": dataset_source_manifest_ref,
        "table_refs": table_refs,
        "row_counts": {
            "batch_rows": len(batches),
            "replicate_rows": len(replicates),
            "phase_rows": len(phases),
            "run_metadata": len(runs),
        },
        "run_count": len({row["benchmark_run_id"] for row in batches}),
        "calendar_day_count": len({row["observed_date"] for row in batches}),
        "methodology_count": len({row["methodology_id"] for row in runs}),
        "latest_run_id": latest_run["benchmark_run_id"],
    }
    poll_manifest = {
        "contract": SANDBOX_WORKLOAD_POLL_CONTRACT,
        "refresh_id": refresh_id,
        "checked_at": checked_at,
        "source_repository": source_repository,
        "source_commit": source_commit,
        "source_capture_manifest_ref": source_manifest_ref,
        "dataset_manifest_ref": dataset_manifest_ref,
        "generation_id": generation_id,
        "changed_from_reviewed_evidence": _stable_rows(batch_rows)
        != _stable_rows(_read_local_json(BENCHMARK_EVIDENCE)["batch_rows"]),
    }
    latest_manifest = {
        **dataset_manifest,
        "latest_checked_at": checked_at,
        "latest_refresh_id": refresh_id,
        "latest_poll_manifest_ref": poll_ref,
        "latest_source_capture_manifest_ref": source_manifest_ref,
    }

    lease_ref = f"{output_root.rstrip('/')}/_locks/workload-benchmark-refresh.json"
    with exclusive_lease(lease_ref):
        existing_manifest = read_optional_json(latest_ref)
        if existing_manifest:
            _assert_no_operational_rewrite(
                existing_manifest=existing_manifest,
                incoming={
                    "sandbox_benchmark_batches": batches,
                    "sandbox_benchmark_replicates": replicates,
                    "sandbox_benchmark_phases": phases,
                    "sandbox_benchmark_run_metadata": runs,
                },
            )
        write_parquet_rows(table_refs["sandbox_benchmark_batches"], batches)
        write_parquet_rows(
            table_refs["sandbox_benchmark_replicates"],
            replicates,
        )
        write_parquet_rows(table_refs["sandbox_benchmark_phases"], phases)
        write_parquet_rows(
            table_refs["sandbox_benchmark_run_metadata"],
            runs,
        )
        write_json(dataset_source_manifest_ref, stable_source_manifest)
        write_json(dataset_manifest_ref, dataset_manifest)
        write_json(poll_ref, poll_manifest)
        write_json(latest_ref, latest_manifest)
    return latest_manifest


def _assert_no_operational_rewrite(
    *,
    existing_manifest: dict[str, Any],
    incoming: dict[str, list[dict[str, Any]]],
) -> None:
    """Reject a source that removes or mutates an already published identity."""
    existing_refs = existing_manifest.get("table_refs")
    if not isinstance(existing_refs, dict):
        raise ValueError("Existing workload manifest has no table refs")
    contracts = {
        "sandbox_benchmark_batches": (
            ("series_id", "benchmark_run_id"),
            (
                "runtime_seconds",
                "estimated_cost_usd",
                "hourly_price_usd",
                "job_parts",
                "source_run_sha",
                "task_signature",
                "workload_app_version",
            ),
        ),
        "sandbox_benchmark_replicates": (
            ("series_id", "benchmark_run_id", "replicate_index"),
            (
                "runtime_seconds",
                "estimated_cost_usd",
                "hourly_price_usd",
                "task_count",
                "source_run_sha",
                "task_signature",
            ),
        ),
        "sandbox_benchmark_phases": (
            (
                "series_id",
                "benchmark_run_id",
                "replicate_index",
                "task_id",
            ),
            (
                "runtime_seconds",
                "task_order",
                "source_run_sha",
                "task_signature",
            ),
        ),
        "sandbox_benchmark_run_metadata": (
            ("benchmark_run_id",),
            (
                "source_run_sha",
                "task_signature",
                "workload_app_version",
                "provider_result_count",
            ),
        ),
    }
    for table_name, (key_fields, stable_fields) in contracts.items():
        existing_ref = existing_refs.get(table_name)
        if not isinstance(existing_ref, str) or not existing_ref:
            raise ValueError(f"Existing workload manifest is missing {table_name}")
        existing_rows = read_parquet_rows(existing_ref)
        incoming_rows = incoming[table_name]
        merged = _merge_rows(
            existing_rows,
            incoming_rows,
            key_fields=key_fields,
            stable_fields=stable_fields,
        )
        if len(merged) != len(incoming_rows):
            incoming_keys = {
                tuple(str(row[field]) for field in key_fields) for row in incoming_rows
            }
            missing = [
                tuple(str(row[field]) for field in key_fields)
                for row in existing_rows
                if tuple(str(row[field]) for field in key_fields) not in incoming_keys
            ]
            raise ValueError(
                f"Operational workload source removed retained {table_name} "
                f"identities: {missing[:5]}"
            )
