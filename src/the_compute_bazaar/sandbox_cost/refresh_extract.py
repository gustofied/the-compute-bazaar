"""Extract normalized observations from StarSling benchmark runs."""

from __future__ import annotations

from .refresh_support import REPOSITORY, _parse_timestamp, _validate_source_repository

import hashlib
import json
from collections import defaultdict
from typing import Any


from .evidence import (
    RUNTIME_PRICE_SERIES,
    TARGET_SHAPE,
)


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

            replicate_counts = {int(metric["aggregates"]["n"]) for metric in metrics}
            if len(replicate_counts) != 1:
                raise ValueError(
                    f"Schema drift: {run_id} {source_id} task sample counts differ"
                )
            replicate_count = replicate_counts.pop()
            replicate_maps = _replicate_samples(metrics)
            replicate_data_available = replicate_maps is not None
            run_replicate_indexed = run_replicate_indexed or replicate_data_available
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
                                "benchmark_source_url": common["benchmark_source_url"],
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
        raise ValueError(f"Workload drift: {run_id} {provider_id} task IDs changed")
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
        raise ValueError(f"Workload drift: {run_id} {provider_id} app version changed")
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
