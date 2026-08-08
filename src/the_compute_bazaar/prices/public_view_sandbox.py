"""Build the public StarSling workload-cost card."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .public_view_common import card, number, observation_window, without


def sandbox_workload_view(payload: Mapping[str, Any]) -> dict[str, Any]:
    manifest = payload.get("manifest") or {}
    workload = payload.get("workload") or {}
    summaries = list(workload.get("service_summary") or [])
    latest_run = workload.get("latest_run") or {}
    run_history = list(workload.get("run_history") or [])
    complete_runs = [
        row
        for row in run_history
        if isinstance(row, Mapping) and row.get("service_set_complete") is True
    ]
    latest_complete_run = (
        complete_runs[-1] if complete_runs else run_history[-1] if run_history else {}
    )
    timestamps = [
        {"observed_at": row.get("observed_at") or row.get("observed_date")}
        for row in run_history
        if isinstance(row, Mapping)
    ]
    return card(
        manifest=dict(manifest),
        card_type="sandbox_workload_cost",
        card_id="sandbox:workload",
        as_of=latest_run.get("generated_at") or manifest.get("built_at"),
        status="live" if summaries else "unavailable",
        unit="USD per completed benchmark job",
        methodology={
            "cost_basis": workload.get("cost_basis"),
            "runtime_definition": workload.get("runtime_definition"),
            "claim_scope": workload.get("claim_scope"),
        },
        headline={
            "label": "Latest StarSling workload cost",
            "median_estimated_cost_usd": number(
                latest_complete_run.get("median_estimated_cost_usd")
            ),
            "median_runtime_seconds": number(
                latest_complete_run.get("median_runtime_seconds")
            ),
            "service_count": len(summaries),
            "complete_job_count": int(workload.get("latest_replicate_count") or 0),
            "incomplete_slot_count": int(
                workload.get("latest_incomplete_replicate_count") or 0
            ),
            "total_source_replicate_slot_count": int(
                workload.get("latest_replicate_count") or 0
            )
            + int(workload.get("latest_incomplete_replicate_count") or 0),
            "source_replicate_slot_count": int(
                workload.get("latest_source_replicate_slot_count") or 0
            ),
            "benchmark_run_id": latest_complete_run.get("benchmark_run_id"),
            "observed_at": latest_complete_run.get("generated_at")
            or latest_complete_run.get("observed_date"),
        },
        series=run_history,
        band={
            "kind": "observed_job_distribution",
            "lower_field": "p25",
            "upper_field": "p75",
        },
        coverage={
            "source_batch_count": int(workload.get("source_batch_count") or 0),
            "calendar_day_count": int(workload.get("calendar_day_count") or 0),
            "service_count": len(summaries),
            "latest_replicate_count": int(workload.get("latest_replicate_count") or 0),
        },
        sources=list(payload.get("sources") or []),
        drilldown_ref="sandbox/workload.json",
        data={
            "manifest": dict(manifest),
            "workload": without(workload, "run_history"),
            "credit": {
                "name": "StarSling HPC Sandbox Benchmark",
                "url": "https://github.com/starslingdev/hpc-sandbox-benchmarks",
            },
        },
        observation_window=observation_window(timestamps),
    )
