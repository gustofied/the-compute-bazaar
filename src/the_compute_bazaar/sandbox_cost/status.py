"""Read sandbox build state and validate public snapshot freshness."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from .evidence import _parse_timestamp


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
    checked_at = _as_utc(checked_at)

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
