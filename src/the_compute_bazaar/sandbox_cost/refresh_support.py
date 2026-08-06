"""Fetch, merge, and stabilize StarSling source history."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from .evidence import (
    EVIDENCE_ROOT,
)


REPOSITORY = "starslingdev/hpc-sandbox-benchmarks"

EXPECTED_INDEX_FIELDS = {"schemaVersion", "runs"}

EXPECTED_INDEX_ROW_FIELDS = {"runId", "generatedAt", "path"}


def _validate_source_repository(value: str) -> str:
    parts = value.strip().split("/")
    if (
        len(parts) != 2
        or not all(parts)
        or any(not part.replace("-", "").replace("_", "").isalnum() for part in parts)
    ):
        raise ValueError("source_repository must be a GitHub owner/repository slug")
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
        raise ValueError("Schema drift in benchmark index: expected schemaVersion '1'")
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
                if field in previous and field in row and previous[field] != row[field]
            ]
            if changed:
                raise ValueError(
                    f"Source changed an existing benchmark result: {key} "
                    f"({', '.join(changed)})"
                )
        rows[key] = dict(row)
    return sorted(
        rows.values(), key=lambda row: tuple(str(row[field]) for field in key_fields)
    )


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
