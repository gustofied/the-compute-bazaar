"""Build the public StarSling workload-cost payload."""

from __future__ import annotations


from typing import Any


def build_public_payload(
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
    expected_service_count: int,
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
            "contract": manifest["contract"],
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
            "expected_service_count": expected_service_count,
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
