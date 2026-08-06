"""Refresh public StarSling benchmark evidence without guessing price changes."""

from __future__ import annotations

from .refresh_extract import (
    TASK_ARGUMENTS,
    TASK_PREFIX,
    TASK_SOURCE_FILE,
    WORKLOAD_APP_VERSION,
    _has_target_job,
    extract_benchmark_evidence,
)
from .refresh_operational import _publish_operational_benchmark
from .refresh_support import (
    REPOSITORY,
    _fetch_bytes,
    _merge_historical_rows,
    _merge_rows,
    _parse_index,
    _resolve_commit,
    _stable_rows,
    _target_shape,
    _validate_source_repository,
    _write_local_json,
)

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

import requests

from .evidence import (
    BENCHMARK_EVIDENCE,
    SOURCE_MANIFEST,
    TARGET_SHAPE,
    WORKLOAD_COST_INPUTS,
    _read_local_json,
    _validate_prices,
    write_source_capture,
)
from the_compute_bazaar.prices.storage import (
    write_json,
)


def refresh_benchmark_sources(
    *,
    output_root: str = "data/sandbox-cost",
    source_ref: str = "main",
    source_repository: str = REPOSITORY,
    update_evidence: bool = False,
    publish_operational: bool = False,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    """Fetch commit-pinned public run data, extract rows, and detect drift."""
    source_repository = _validate_source_repository(source_repository)
    api_root = f"https://api.github.com/repos/{source_repository}"
    raw_root = f"https://raw.githubusercontent.com/{source_repository}"
    client = session or requests.Session()
    commit = _resolve_commit(client, source_ref, api_root=api_root)
    retrieved = datetime.now(timezone.utc)
    retrieved_at = retrieved.isoformat()
    refresh_id = f"workload-refresh-{retrieved.strftime('%Y%m%dT%H%M%S%fZ')}"
    index_path = "data/dataset/index.json"
    methodology_path = "docs/methodology.md"
    index_bytes = _fetch_bytes(client, f"{raw_root}/{commit}/{index_path}")
    methodology_bytes = _fetch_bytes(client, f"{raw_root}/{commit}/{methodology_path}")
    index = _parse_index(index_bytes)

    captures: dict[str, bytes] = {
        index_path: index_bytes,
        methodology_path: methodology_bytes,
    }
    runs: list[dict[str, Any]] = []
    rejected_shapes: dict[str, dict[str, int]] = {}
    for entry in index["runs"]:
        run_id = str(entry["runId"])
        if "+" in run_id:
            continue
        path = f"data/dataset/{entry['path']}"
        raw = _fetch_bytes(client, f"{raw_root}/{commit}/{path}")
        captures[path] = raw
        run = json.loads(raw)
        if not isinstance(run, dict):
            raise ValueError(f"Schema drift: {path} is not a JSON object")
        if not _has_target_job(run):
            continue
        shape = _target_shape(run)
        if shape != TARGET_SHAPE:
            rejected_shapes[run_id] = shape
            continue
        runs.append(run)

    price_payload = _read_local_json(WORKLOAD_COST_INPUTS)
    prices = _validate_prices(price_payload["rows"])
    extracted = extract_benchmark_evidence(
        runs=runs,
        prices=prices,
        source_commit=commit,
        source_repository=source_repository,
    )
    canonical = _read_local_json(BENCHMARK_EVIDENCE)
    canonical_batches = canonical.get("batch_rows", canonical.get("rows", []))
    merged_batches = _merge_historical_rows(
        canonical_batches,
        extracted["batch_rows"],
    )
    merged_replicates = _merge_rows(
        canonical.get("replicate_rows", []),
        extracted["replicate_rows"],
        key_fields=("series_id", "benchmark_run_id", "replicate_index"),
        stable_fields=("runtime_seconds", "task_count"),
    )
    merged_phases = _merge_rows(
        canonical.get("phase_rows", []),
        extracted["phase_rows"],
        key_fields=(
            "series_id",
            "benchmark_run_id",
            "replicate_index",
            "task_id",
        ),
        stable_fields=("runtime_seconds", "task_order"),
    )
    merged_runs = _merge_rows(
        canonical.get("run_metadata", []),
        extracted["run_metadata"],
        key_fields=("benchmark_run_id",),
        stable_fields=(
            "source_run_sha",
            "task_signature",
            "workload_app_version",
        ),
    )
    changed = (
        canonical.get("schema_version") != "sandbox_benchmark_observation_v2"
        or _stable_rows(canonical_batches) != _stable_rows(merged_batches)
        or canonical.get("replicate_rows", []) != merged_replicates
        or canonical.get("phase_rows", []) != merged_phases
        or canonical.get("run_metadata", []) != merged_runs
    )

    repository_partition = source_repository.replace("/", "--")
    capture_prefix = (
        f"{output_root.rstrip('/')}/bronze/hpc-sandbox-benchmarks/"
        f"source={repository_partition}/commit={commit}/refresh_id={refresh_id}"
    )
    source_files = []
    for path, raw in sorted(captures.items()):
        capture_ref = f"{capture_prefix}/{path}"
        write_source_capture(capture_ref, raw)
        source_files.append(
            {
                "path": path,
                "source_url": (
                    f"https://github.com/{source_repository}/blob/{commit}/{path}"
                ),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "size_bytes": len(raw),
            }
        )
    runtime_manifest = {
        "schema_version": "sandbox_source_manifest_v1",
        "retrieved_at": retrieved_at,
        "source_repository": source_repository,
        "source_commit": commit,
        "files": source_files,
        "notes": [
            "Raw public files are captured under the commit-pinned bronze prefix.",
            "Unlike machine shapes are retained in bronze and rejected before silver.",
        ],
    }
    manifest_ref = f"{capture_prefix}/source-manifest.json"
    write_json(manifest_ref, runtime_manifest)

    operational_manifest_ref = None
    operational_table_refs: dict[str, str] = {}
    if publish_operational:
        operational = _publish_operational_benchmark(
            output_root=output_root,
            source_repository=source_repository,
            source_commit=commit,
            checked_at=retrieved_at,
            refresh_id=refresh_id,
            source_manifest=runtime_manifest,
            source_manifest_ref=manifest_ref,
            prices=prices,
            batch_rows=merged_batches,
            replicate_rows=merged_replicates,
            phase_rows=merged_phases,
            run_metadata=merged_runs,
        )
        operational_manifest_ref = str(operational["manifest_ref"])
        operational_table_refs = dict(operational["table_refs"])

    if update_evidence and changed:
        benchmark_payload = {
            "schema_version": "sandbox_benchmark_observation_v2",
            "retrieved_at": retrieved_at,
            "source_repository": source_repository,
            "source_commit": commit,
            "target_shape": TARGET_SHAPE,
            "job": {
                "id": "better-auth-ten-task-sum",
                "source_file": TASK_SOURCE_FILE,
                "metric_prefix": TASK_PREFIX,
                "app_version": WORKLOAD_APP_VERSION,
                "parts": len(TASK_ARGUMENTS),
                "task_arguments": [argument for argument, _ in TASK_ARGUMENTS],
            },
            "formula": ("runtime_seconds / 3600 * hourly_price_usd"),
            "runtime_definition": (
                "Batch rows sum ten published task means. Replicate rows sum "
                "ten task samples carrying the same upstream replicate index. "
                "Neither includes sandbox startup, teardown, retries, or "
                "unmeasured task preparation."
            ),
            "batch_rows": merged_batches,
            "replicate_rows": merged_replicates,
            "phase_rows": merged_phases,
            "run_metadata": merged_runs,
        }
        _write_local_json(BENCHMARK_EVIDENCE, benchmark_payload)
        _write_local_json(SOURCE_MANIFEST, runtime_manifest)

    return {
        "source_commit": commit,
        "source_run_count": len(runs),
        "extracted_batch_count": len(extracted["batch_rows"]),
        "extracted_replicate_count": len(extracted["replicate_rows"]),
        "extracted_phase_count": len(extracted["phase_rows"]),
        "merged_batch_count": len(merged_batches),
        "merged_replicate_count": len(merged_replicates),
        "merged_phase_count": len(merged_phases),
        "new_batch_count": len(merged_batches) - len(canonical_batches),
        "changed": changed,
        "updated_evidence": bool(update_evidence and changed),
        "rejected_shapes": rejected_shapes,
        "bronze_manifest_ref": manifest_ref,
        "operational_manifest_ref": operational_manifest_ref,
        "operational_table_refs": operational_table_refs,
    }
