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
    _validate_prices,
    write_source_capture,
)


REPOSITORY = "starslingdev/hpc-sandbox-benchmarks"
API_ROOT = f"https://api.github.com/repos/{REPOSITORY}"
RAW_ROOT = f"https://raw.githubusercontent.com/{REPOSITORY}"
TASK_SOURCE_FILE = "realworld-better-auth/pts_realworld-better-auth.xml"
TASK_PREFIX = "realworld_better_auth_task_"
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
    update_evidence: bool = False,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    """Fetch commit-pinned public run data, extract rows, and detect drift."""
    client = session or requests.Session()
    commit = _resolve_commit(client, source_ref)
    retrieved_at = datetime.now(timezone.utc).isoformat()
    index_path = "data/dataset/index.json"
    methodology_path = "docs/methodology.md"
    index_bytes = _fetch_bytes(client, f"{RAW_ROOT}/{commit}/{index_path}")
    methodology_bytes = _fetch_bytes(
        client, f"{RAW_ROOT}/{commit}/{methodology_path}"
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
        raw = _fetch_bytes(client, f"{RAW_ROOT}/{commit}/{path}")
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
    extracted_rows = extract_benchmark_rows(
        runs=runs,
        prices=prices,
        source_commit=commit,
    )
    canonical = _read_local_json(BENCHMARK_EVIDENCE)
    merged_rows = _merge_historical_rows(canonical["rows"], extracted_rows)
    changed = _stable_rows(canonical["rows"]) != _stable_rows(merged_rows)

    capture_prefix = (
        f"{output_root.rstrip('/')}/bronze/hpc-sandbox-benchmarks/"
        f"commit={commit}"
    )
    source_files = []
    for path, raw in sorted(captures.items()):
        capture_ref = f"{capture_prefix}/{path}"
        write_source_capture(capture_ref, raw)
        source_files.append(
            {
                "path": path,
                "source_url": (
                    f"https://github.com/{REPOSITORY}/blob/{commit}/{path}"
                ),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "size_bytes": len(raw),
            }
        )
    runtime_manifest = {
        "schema_version": "sandbox_source_manifest_v1",
        "retrieved_at": retrieved_at,
        "source_repository": REPOSITORY,
        "source_commit": commit,
        "files": source_files,
        "notes": [
            "Raw public files are captured under the commit-pinned bronze prefix.",
            "Unlike machine shapes are retained in bronze and rejected before silver.",
        ],
    }
    manifest_ref = f"{capture_prefix}/source-manifest.json"
    from the_compute_bazaar.prices.storage import write_json

    write_json(manifest_ref, runtime_manifest)

    if update_evidence and changed:
        benchmark_payload = {
            **canonical,
            "retrieved_at": retrieved_at,
            "source_commit": commit,
            "rows": merged_rows,
        }
        _write_local_json(BENCHMARK_EVIDENCE, benchmark_payload)
        _write_local_json(SOURCE_MANIFEST, runtime_manifest)

    return {
        "source_commit": commit,
        "source_run_count": len(runs),
        "extracted_result_count": len(extracted_rows),
        "merged_result_count": len(merged_rows),
        "new_result_count": len(merged_rows) - len(canonical["rows"]),
        "changed": changed,
        "updated_evidence": bool(update_evidence and changed),
        "rejected_shapes": rejected_shapes,
        "bronze_manifest_ref": manifest_ref,
    }


def extract_benchmark_rows(
    *,
    runs: list[dict[str, Any]],
    prices: list[dict[str, Any]],
    source_commit: str = "main",
) -> list[dict[str, Any]]:
    """Extract every validated shape-compatible Better Auth service result."""
    price_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in prices:
        price_rows[row["series_id"]].append(row)
    for rows in price_rows.values():
        rows.sort(key=lambda row: row["observed_date"])

    extracted: list[dict[str, Any]] = []
    point_order: dict[str, int] = defaultdict(int)
    ordered_runs = sorted(runs, key=lambda run: _parse_timestamp(run["generatedAt"]))
    for run in ordered_runs:
        run_id = str(run["runId"])
        generated_at = str(run["generatedAt"])
        observed_date = _parse_timestamp(generated_at).date().isoformat()
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
            point_order[series_id] += 1
            extracted.append(
                {
                    "series_order": order,
                    "point_order": point_order[series_id],
                    "series_id": series_id,
                    "series_label": label,
                    "observed_date": observed_date,
                    "generated_at": generated_at,
                    "runtime_seconds": runtime_seconds,
                    "hourly_price_usd": hourly_price,
                    "estimated_cost_usd": estimated_cost,
                    "price_scope": "processor_and_memory_only",
                    "vcpus": TARGET_SHAPE["vcpus"],
                    "memory_gib": TARGET_SHAPE["memory_gib"],
                    "disk_gb": TARGET_SHAPE["disk_gb"],
                    "job_parts": len(metrics),
                    "benchmark_run_id": run_id,
                    "benchmark_source_url": (
                        f"https://github.com/{REPOSITORY}/blob/{source_commit}/"
                        f"data/dataset/runs/{run_id}.json"
                    ),
                    "price_date": price["observed_date"],
                    "price_source_url": price["source_url"],
                    "note": (
                        "Runtime is the sum of ten published mean task times. "
                        "Cost is runtime multiplied by the matching public "
                        "processor-and-memory price; storage, network, plans, "
                        "credits, and retries are excluded."
                    ),
                    "color": color,
                }
            )
    return sorted(
        extracted,
        key=lambda row: (
            row["series_order"],
            row["generated_at"],
            row["point_order"],
        ),
    )


def _resolve_commit(client: requests.Session, ref: str) -> str:
    response = client.get(f"{API_ROOT}/commits/{ref}", timeout=30)
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
    rows: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in [*canonical, *refreshed]:
        key = (
            str(row["series_id"]),
            str(row["generated_at"]),
            str(row["benchmark_run_id"]),
        )
        previous = rows.get(key)
        if previous is not None and _stable_row(previous) != _stable_row(row):
            raise ValueError(f"Source changed an existing benchmark result: {key}")
        rows[key] = dict(row)
    ordered = sorted(
        rows.values(),
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
