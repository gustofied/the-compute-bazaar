"""Refresh public StarSling benchmark evidence without guessing price changes."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from .pipeline import (
    BENCHMARK_EVIDENCE,
    EVIDENCE_ROOT,
    PRICE_EVIDENCE,
    RUNTIME_PRICE_SERIES,
    SOURCE_MANIFEST,
    TARGET_SHAPE,
    _read_local_json,
    _validate_batches,
    _validate_phases,
    _validate_prices,
    _validate_replicates,
    _validate_run_metadata,
    _validate_source_manifest,
    write_source_capture,
)
from the_compute_bazaar.prices.storage import (
    exclusive_lease,
    read_optional_json,
    read_parquet_rows,
    write_json,
    write_parquet_rows,
)


REPOSITORY = "starslingdev/hpc-sandbox-benchmarks"
TASK_SOURCE_FILE = "realworld-better-auth/pts_realworld-better-auth.xml"
TASK_PREFIX = "realworld_better_auth_task_"
WORKLOAD_APP_VERSION = "6f3ba45639579da152b69e8e5342e02f28288670"
TASK_ARGUMENTS = (
    ("git_clone", "realworld_better_auth_task_git_clone"),
    ("cold_install", "realworld_better_auth_task_cold_install"),
    ("build", "realworld_better_auth_task_build"),
    ("lint_biome", "realworld_better_auth_task_lint_biome"),
    ("lint_deps", "realworld_better_auth_task_lint_deps_knip"),
    ("lint_format", "realworld_better_auth_task_lint_format"),
    ("lint_spell", "realworld_better_auth_task_lint_spell"),
    ("lint_types", "realworld_better_auth_task_lint_types"),
    ("lint_packages", "realworld_better_auth_task_lint_packages"),
    ("typecheck", "realworld_better_auth_task_typecheck"),
)
TASK_ORDER = {
    metric_id: (position, argument)
    for position, (argument, metric_id) in enumerate(TASK_ARGUMENTS, start=1)
}
EXPECTED_INDEX_FIELDS = {"schemaVersion", "runs"}
EXPECTED_INDEX_ROW_FIELDS = {"runId", "generatedAt", "path"}

PROVIDER_ALIASES = {
    "blaxel": "blaxel",
    "daytona": "daytona-vm",
    "daytona-vm": "daytona-vm",
    "e2b": "e2b",
    "modal": "modal-gvisor",
    "modal-gvisor": "modal-gvisor",
    "modal-vm": "modal-vm",
    "novita": "novita",
}

SERIES = {
    "blaxel": (1, "Blaxel", "#44617a"),
    "daytona-vm": (2, "Daytona VM", "#2f6b4f"),
    "e2b": (3, "E2B", "#275d87"),
    "modal-gvisor": (4, "Modal gVisor", "#76558f"),
    "modal-vm": (5, "Modal VM", "#9b4f63"),
    "novita": (6, "Novita", "#ad5c16"),
}


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
    methodology_bytes = _fetch_bytes(
        client, f"{raw_root}/{commit}/{methodology_path}"
    )
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

    price_payload = _read_local_json(PRICE_EVIDENCE)
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
            "formula": (
                "runtime_seconds / 3600 * hourly_price_usd"
            ),
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


def extract_benchmark_rows(
    *,
    runs: list[dict[str, Any]],
    prices: list[dict[str, Any]],
    source_commit: str = "main",
    source_repository: str = REPOSITORY,
) -> list[dict[str, Any]]:
    """Extract provider-batch summaries for compatibility with existing callers."""
    return extract_benchmark_evidence(
        runs=runs,
        prices=prices,
        source_commit=source_commit,
        source_repository=source_repository,
    )["batch_rows"]


def extract_benchmark_evidence(
    *,
    runs: list[dict[str, Any]],
    prices: list[dict[str, Any]],
    source_commit: str = "main",
    source_repository: str = REPOSITORY,
) -> dict[str, list[dict[str, Any]]]:
    """Extract batches, aligned replicates, phases, and run methodology."""
    source_repository = _validate_source_repository(source_repository)
    price_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in prices:
        price_rows[row["series_id"]].append(row)
    for rows in price_rows.values():
        rows.sort(key=lambda row: row["observed_date"])

    batches: list[dict[str, Any]] = []
    replicates: list[dict[str, Any]] = []
    phases: list[dict[str, Any]] = []
    run_metadata: list[dict[str, Any]] = []
    point_order: dict[str, int] = defaultdict(int)
    ordered_runs = sorted(runs, key=lambda run: _parse_timestamp(run["generatedAt"]))
    for run in ordered_runs:
        run_id = str(run["runId"])
        generated_at = str(run["generatedAt"])
        source_run_sha = str(run.get("sha", ""))
        if len(source_run_sha) != 40:
            raise ValueError(f"Schema drift: {run_id} has no full source SHA")
        observed_date = _parse_timestamp(generated_at).date().isoformat()
        run_task_signature: str | None = None
        run_methodology_id: str | None = None
        run_app_version: str | None = None
        run_replicate_indexed = False
        provider_result_count = 0
        for provider in run.get("providers", []):
            source_id = str(provider.get("providerId", ""))
            series_id = PROVIDER_ALIASES.get(source_id)
            if series_id is None:
                continue
            if provider.get("validationStatus") != "validated":
                continue
            if provider.get("specMatched") is not True:
                continue
            metrics = _task_metrics(provider)
            if not metrics:
                continue
            if len(metrics) != 10:
                raise ValueError(
                    f"Schema drift: {run_id} {source_id} has "
                    f"{len(metrics)} Better Auth task parts"
                )
            task_signature, app_version = _validate_workload_metrics(
                metrics,
                run_id=run_id,
                provider_id=source_id,
            )
            methodology_id = (
                f"starsling-better-auth-{source_run_sha[:12]}-{task_signature[:8]}"
            )
            if run_task_signature not in (None, task_signature):
                raise ValueError(
                    f"Schema drift: {run_id} contains multiple task signatures"
                )
            if run_app_version not in (None, app_version):
                raise ValueError(
                    f"Schema drift: {run_id} contains multiple workload versions"
                )
            if run_methodology_id not in (None, methodology_id):
                raise ValueError(
                    f"Schema drift: {run_id} contains multiple methodologies"
                )
            run_task_signature = task_signature
            run_app_version = app_version
            run_methodology_id = methodology_id
            provider_result_count += 1

            replicate_counts = {
                int(metric["aggregates"]["n"]) for metric in metrics
            }
            if len(replicate_counts) != 1:
                raise ValueError(
                    f"Schema drift: {run_id} {source_id} task sample counts differ"
                )
            replicate_count = replicate_counts.pop()
            replicate_maps = _replicate_samples(metrics)
            replicate_data_available = replicate_maps is not None
            run_replicate_indexed = (
                run_replicate_indexed or replicate_data_available
            )
            runtime_seconds = round(
                sum(float(metric["aggregates"]["mean"]) for metric in metrics),
                6,
            )
            price_series = RUNTIME_PRICE_SERIES[series_id]
            candidates = [
                price
                for price in price_rows[price_series]
                if price["observed_date"] <= observed_date
            ]
            if not candidates:
                raise ValueError(
                    f"No {price_series} price at or before {observed_date}"
                )
            price = candidates[-1]
            hourly_price = float(price["price_usd_per_hour"])
            estimated_cost = round(runtime_seconds * hourly_price / 3600, 9)
            order, label, color = SERIES[series_id]
            observed = provider.get("observedSpecs")
            if observed is None:
                observed = {}
            if not isinstance(observed, dict):
                raise ValueError(
                    f"Schema drift: {run_id} {source_id} observedSpecs is not an object"
                )
            workload_gaps = [
                gap
                for gap in provider.get("gaps", [])
                if gap.get("id") == "realworld-better-auth"
            ]
            point_order[series_id] += 1
            common = {
                "series_order": order,
                "series_id": series_id,
                "series_label": label,
                "observed_date": observed_date,
                "generated_at": generated_at,
                "hourly_price_usd": hourly_price,
                "price_scope": "processor_and_memory_only",
                "vcpus": TARGET_SHAPE["vcpus"],
                "memory_gib": TARGET_SHAPE["memory_gib"],
                "disk_gb": TARGET_SHAPE["disk_gb"],
                "observed_vcpus": _optional_number(observed.get("vcpus")),
                "observed_memory_gib": _optional_number(observed.get("memoryGb")),
                "observed_disk_gb": _optional_number(observed.get("diskGb")),
                "cpu_model": _optional_text(observed.get("cpuModel")),
                "virtualization": _optional_text(observed.get("virtualization")),
                "country": _optional_text(observed.get("country")),
                "region": _optional_text(observed.get("region")),
                "city": _optional_text(observed.get("city")),
                "egress_asn": _optional_text(observed.get("egressAsn")),
                "job_parts": len(metrics),
                "benchmark_run_id": run_id,
                "source_run_sha": source_run_sha,
                "workload_app_version": app_version,
                "task_signature": task_signature,
                "methodology_id": methodology_id,
                "benchmark_source_url": (
                    f"https://github.com/{source_repository}/blob/{source_commit}/"
                    f"data/dataset/runs/{run_id}.json"
                ),
                "price_date": price["observed_date"],
                "price_source_url": price["source_url"],
                "cost_basis": "public_rate_card_unmetered",
                "lifecycle_included": False,
                "workload_gap_count": len(workload_gaps),
                "color": color,
            }
            batches.append(
                {
                    **common,
                    "point_order": point_order[series_id],
                    "runtime_seconds": runtime_seconds,
                    "estimated_cost_usd": estimated_cost,
                    "replicate_count": replicate_count,
                    "replicate_data_available": replicate_data_available,
                    "observation_level": "provider_batch_summary",
                    "runtime_basis": "sum_of_published_task_means",
                    "note": (
                        "Provider-batch summary: runtime is the sum of ten "
                        "published task means. Cost is an unmetered rate-card "
                        "estimate. Startup, teardown, retries, storage, network, "
                        "plans, credits, and unmeasured preparation are excluded."
                    ),
                }
            )
            if replicate_maps is not None:
                replicate_indices = sorted(next(iter(replicate_maps.values())))
                for replicate_index in replicate_indices:
                    replicate_runtime = round(
                        sum(
                            replicate_maps[metric_id][replicate_index]
                            for _, metric_id in TASK_ARGUMENTS
                        ),
                        6,
                    )
                    replicate_cost = round(
                        replicate_runtime * hourly_price / 3600,
                        9,
                    )
                    replicates.append(
                        {
                            **common,
                            "replicate_index": replicate_index,
                            "runtime_seconds": replicate_runtime,
                            "estimated_cost_usd": replicate_cost,
                            "task_count": len(metrics),
                            "observation_level": "aligned_job_replicate",
                            "runtime_basis": (
                                "sum_of_ten_task_samples_with_same_replicate_index"
                            ),
                        }
                    )
                    for argument, metric_id in TASK_ARGUMENTS:
                        task_order, _ = TASK_ORDER[metric_id]
                        phases.append(
                            {
                                "series_order": order,
                                "series_id": series_id,
                                "series_label": label,
                                "observed_date": observed_date,
                                "generated_at": generated_at,
                                "benchmark_run_id": run_id,
                                "source_run_sha": source_run_sha,
                                "methodology_id": methodology_id,
                                "workload_app_version": app_version,
                                "task_signature": task_signature,
                                "replicate_index": replicate_index,
                                "task_order": task_order,
                                "task_id": metric_id,
                                "task_label": argument,
                                "runtime_seconds": replicate_maps[metric_id][
                                    replicate_index
                                ],
                                "benchmark_source_url": common[
                                    "benchmark_source_url"
                                ],
                                "color": color,
                            }
                        )
        if provider_result_count:
            run_metadata.append(
                {
                    "benchmark_run_id": run_id,
                    "generated_at": generated_at,
                    "source_run_sha": source_run_sha,
                    "methodology_id": run_methodology_id,
                    "workload_app_version": run_app_version,
                    "task_signature": run_task_signature,
                    "target_vcpus": TARGET_SHAPE["vcpus"],
                    "target_memory_gib": TARGET_SHAPE["memory_gib"],
                    "target_disk_gb": TARGET_SHAPE["disk_gb"],
                    "task_count": len(TASK_ARGUMENTS),
                    "provider_result_count": provider_result_count,
                    "replicate_indexed": run_replicate_indexed,
                    "runtime_basis": "sum_of_published_task_means",
                    "lifecycle_included": False,
                    "benchmark_source_url": (
                        f"https://github.com/{source_repository}/blob/{source_commit}/"
                        f"data/dataset/runs/{run_id}.json"
                    ),
                }
            )
    return {
        "batch_rows": sorted(
            batches,
            key=lambda row: (
                row["series_order"],
                row["generated_at"],
                row["point_order"],
            ),
        ),
        "replicate_rows": sorted(
            replicates,
            key=lambda row: (
                row["series_order"],
                row["generated_at"],
                row["replicate_index"],
            ),
        ),
        "phase_rows": sorted(
            phases,
            key=lambda row: (
                row["series_order"],
                row["generated_at"],
                row["replicate_index"],
                row["task_order"],
            ),
        ),
        "run_metadata": sorted(
            run_metadata,
            key=lambda row: row["generated_at"],
        ),
    }


def _validate_workload_metrics(
    metrics: list[dict[str, Any]],
    *,
    run_id: str,
    provider_id: str,
) -> tuple[str, str]:
    expected_ids = set(TASK_ORDER)
    observed_ids = {str(metric.get("metricId")) for metric in metrics}
    if observed_ids != expected_ids:
        raise ValueError(
            f"Workload drift: {run_id} {provider_id} task IDs changed"
        )
    normalized = []
    app_versions = set()
    for metric in metrics:
        metric_id = str(metric["metricId"])
        _, expected_argument = TASK_ORDER[metric_id]
        argument = str(metric.get("arguments", ""))
        if argument != expected_argument:
            raise ValueError(
                f"Workload drift: {run_id} {provider_id} {metric_id} "
                f"expected argument {expected_argument!r}, found {argument!r}"
            )
        app_version = str(metric.get("appVersion", ""))
        app_versions.add(app_version)
        normalized.append(
            {
                "metric_id": metric_id,
                "argument": argument,
                "app_version": app_version,
                "source_file": metric.get("sourceFile"),
            }
        )
    if app_versions != {WORKLOAD_APP_VERSION}:
        raise ValueError(
            f"Workload drift: {run_id} {provider_id} app version changed"
        )
    payload = json.dumps(
        sorted(normalized, key=lambda row: row["metric_id"]),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest(), WORKLOAD_APP_VERSION


def _replicate_samples(
    metrics: list[dict[str, Any]],
) -> dict[str, dict[int, float]] | None:
    if not all(isinstance(metric.get("replicates"), list) for metric in metrics):
        return None
    by_metric: dict[str, dict[int, float]] = {}
    expected_indices: set[int] | None = None
    for metric in metrics:
        samples: dict[int, float] = {}
        for replicate in metric["replicates"]:
            if not isinstance(replicate, dict):
                raise ValueError("Schema drift: replicate must be an object")
            index = int(replicate["index"])
            values = replicate.get("samples")
            if not isinstance(values, list) or len(values) != 1:
                raise ValueError(
                    "Cannot form a job replicate from a non-singleton task sample"
                )
            if index in samples:
                raise ValueError(f"Duplicate replicate index {index}")
            samples[index] = float(values[0])
        indices = set(samples)
        if expected_indices is None:
            expected_indices = indices
        elif indices != expected_indices:
            raise ValueError("Replicate indices are not aligned across all tasks")
        by_metric[str(metric["metricId"])] = samples
    return by_metric if expected_indices else None


def _optional_number(value: Any) -> float | None:
    return None if value is None else float(value)


def _optional_text(value: Any) -> str | None:
    return None if value in (None, "") else str(value)


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
    """Publish a trusted benchmark dataset generation for the hourly gold build."""
    batches = _validate_batches(batch_rows, prices)
    replicates = _validate_replicates(replicate_rows, prices, batches)
    phases = _validate_phases(phase_rows, replicates)
    runs = _validate_run_metadata(run_metadata, batches, replicates)
    _validate_source_manifest(source_manifest, batches)

    stable_source_manifest = {
        "schema_version": "sandbox_source_manifest_v1",
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
        "sandbox_benchmark_run_metadata": (
            f"{generation_prefix}/run_metadata.parquet"
        ),
    }
    dataset_source_manifest_ref = f"{generation_prefix}/source-manifest.json"
    dataset_manifest_ref = f"{generation_prefix}/manifest.json"
    latest_ref = (
        f"{output_root.rstrip('/')}/silver/_manifests/"
        "workload_benchmark/latest.json"
    )
    poll_ref = (
        f"{output_root.rstrip('/')}/silver/_manifests/workload_benchmark/"
        f"polls/date={checked_at[:10]}/refresh_id={refresh_id}.json"
    )
    latest_run = max(runs, key=lambda row: str(row["generated_at"]))
    dataset_manifest = {
        "manifest_version": "sandbox_workload_dataset_v1",
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
        "manifest_version": "sandbox_workload_poll_v1",
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

    lease_ref = (
        f"{output_root.rstrip('/')}/_locks/workload-benchmark-refresh.json"
    )
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
            raise ValueError(
                f"Existing workload manifest is missing {table_name}"
            )
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
                tuple(str(row[field]) for field in key_fields)
                for row in incoming_rows
            }
            missing = [
                tuple(str(row[field]) for field in key_fields)
                for row in existing_rows
                if tuple(str(row[field]) for field in key_fields)
                not in incoming_keys
            ]
            raise ValueError(
                f"Operational workload source removed retained {table_name} "
                f"identities: {missing[:5]}"
            )


def _validate_source_repository(value: str) -> str:
    parts = value.strip().split("/")
    if (
        len(parts) != 2
        or not all(parts)
        or any(not part.replace("-", "").replace("_", "").isalnum() for part in parts)
    ):
        raise ValueError(
            "source_repository must be a GitHub owner/repository slug"
        )
    return "/".join(parts)


def _resolve_commit(
    client: requests.Session,
    ref: str,
    *,
    api_root: str,
) -> str:
    response = client.get(f"{api_root}/commits/{ref}", timeout=30)
    response.raise_for_status()
    payload = response.json()
    sha = payload.get("sha")
    if not isinstance(sha, str) or len(sha) != 40:
        raise ValueError("GitHub commit response did not contain a full SHA")
    return sha


def _fetch_bytes(client: requests.Session, url: str) -> bytes:
    response = client.get(url, timeout=60)
    response.raise_for_status()
    return response.content


def _parse_index(raw: bytes) -> dict[str, Any]:
    payload = json.loads(raw)
    if not isinstance(payload, dict) or set(payload) != EXPECTED_INDEX_FIELDS:
        raise ValueError(
            "Schema drift in benchmark index: expected only "
            f"{sorted(EXPECTED_INDEX_FIELDS)}"
        )
    if payload["schemaVersion"] != "1":
        raise ValueError(
            "Schema drift in benchmark index: expected schemaVersion '1'"
        )
    if not isinstance(payload["runs"], list):
        raise ValueError("Schema drift in benchmark index: runs must be a list")
    for position, row in enumerate(payload["runs"]):
        if not isinstance(row, dict) or set(row) != EXPECTED_INDEX_ROW_FIELDS:
            raise ValueError(
                f"Schema drift in benchmark index row {position}: expected "
                f"{sorted(EXPECTED_INDEX_ROW_FIELDS)}"
            )
        _parse_timestamp(row["generatedAt"])
        if row["path"] != f"runs/{row['runId']}.json":
            raise ValueError(
                f"Unexpected benchmark run path for {row['runId']}: {row['path']}"
            )
    return payload


def _task_metrics(provider: dict[str, Any]) -> list[dict[str, Any]]:
    metrics = provider.get("metrics", [])
    if not isinstance(metrics, list):
        raise ValueError("Schema drift: provider metrics must be a list")
    return [
        metric
        for metric in metrics
        if metric.get("sourceFile") == TASK_SOURCE_FILE
        and str(metric.get("metricId", "")).startswith(TASK_PREFIX)
    ]


def _has_target_job(run: dict[str, Any]) -> bool:
    providers = run.get("providers")
    if not isinstance(providers, list):
        raise ValueError("Schema drift: benchmark run providers must be a list")
    return any(_task_metrics(provider) for provider in providers)


def _target_shape(run: dict[str, Any]) -> dict[str, int]:
    target = run.get("targetSpec")
    if not isinstance(target, dict):
        raise ValueError("Schema drift: benchmark run targetSpec must be an object")
    expected = {"vcpus", "memoryGb", "diskGb"}
    if set(target) != expected:
        raise ValueError(
            f"Schema drift in targetSpec: expected {sorted(expected)}, "
            f"found {sorted(target)}"
        )
    return {
        "vcpus": int(target["vcpus"]),
        "memory_gib": int(target["memoryGb"]),
        "disk_gb": int(target["diskGb"]),
    }


def _parse_timestamp(value: Any) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _merge_historical_rows(
    canonical: list[dict[str, Any]],
    refreshed: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    ordered = _merge_rows(
        canonical,
        refreshed,
        key_fields=("series_id", "generated_at", "benchmark_run_id"),
        stable_fields=("runtime_seconds", "job_parts"),
    )
    ordered.sort(
        key=lambda row: (
            int(row["series_order"]),
            str(row["generated_at"]),
            str(row["benchmark_run_id"]),
        ),
    )
    point_order: dict[str, int] = defaultdict(int)
    for row in ordered:
        point_order[row["series_id"]] += 1
        row["point_order"] = point_order[row["series_id"]]
    return ordered


def _merge_rows(
    canonical: list[dict[str, Any]],
    refreshed: list[dict[str, Any]],
    *,
    key_fields: tuple[str, ...],
    stable_fields: tuple[str, ...],
) -> list[dict[str, Any]]:
    rows: dict[tuple[str, ...], dict[str, Any]] = {}
    for row in [*canonical, *refreshed]:
        key = tuple(str(row[field]) for field in key_fields)
        previous = rows.get(key)
        if previous is not None:
            changed = [
                field
                for field in stable_fields
                if field in previous
                and field in row
                and previous[field] != row[field]
            ]
            if changed:
                raise ValueError(
                    f"Source changed an existing benchmark result: {key} "
                    f"({', '.join(changed)})"
                )
        rows[key] = dict(row)
    return sorted(rows.values(), key=lambda row: tuple(str(row[field]) for field in key_fields))


def _stable_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        (_stable_row(row) for row in rows),
        key=lambda row: (
            row["series_id"],
            row["generated_at"],
            row["benchmark_run_id"],
        ),
    )


def _stable_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key != "point_order"}


def _write_local_json(path: Path, value: dict[str, Any]) -> None:
    if EVIDENCE_ROOT not in path.parents:
        raise ValueError(f"Refusing to update evidence outside {EVIDENCE_ROOT}")
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
