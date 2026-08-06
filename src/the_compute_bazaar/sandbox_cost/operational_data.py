"""Load and validate recurring StarSling datasets."""

from __future__ import annotations

from .evidence import (
    TARGET_SHAPE,
    _validate_batches,
    _validate_phases,
    _validate_replicates,
    _validate_run_metadata,
    _validate_source_manifest,
)

from typing import Any, Mapping

from the_compute_bazaar.contracts import (
    SANDBOX_WORKLOAD_DATASET_CONTRACT,
    transform_contract,
)
from the_compute_bazaar.prices.storage import (
    read_json,
    read_parquet_rows,
)


def load_optional_json(ref: str | None) -> dict[str, Any]:
    if not ref:
        return {}
    try:
        value = read_json(ref)
    except FileNotFoundError:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"Expected JSON object at {ref}")
    return dict(value)


def load_operational_workload_benchmark(
    *,
    manifest: dict[str, Any],
    prices: list[dict[str, Any]],
    canonical_payload: dict[str, Any],
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    """Load and validate the latest trusted recurring workload generation."""
    manifest = transform_contract(
        manifest,
        contract=SANDBOX_WORKLOAD_DATASET_CONTRACT,
    )
    if manifest.get("target_shape") != TARGET_SHAPE:
        raise ValueError(
            "Recurring workload manifest has an incompatible machine shape"
        )
    expected_tables = {
        "sandbox_benchmark_batches",
        "sandbox_benchmark_replicates",
        "sandbox_benchmark_phases",
        "sandbox_benchmark_run_metadata",
    }
    table_refs = manifest.get("table_refs")
    if not isinstance(table_refs, dict) or set(table_refs) != expected_tables:
        raise ValueError(
            "Recurring workload manifest table refs drifted: expected "
            f"{sorted(expected_tables)}"
        )
    if not all(isinstance(ref, str) and ref for ref in table_refs.values()):
        raise ValueError("Recurring workload table refs must be non-empty strings")

    source_manifest_ref = manifest.get("source_manifest_ref")
    if not isinstance(source_manifest_ref, str) or not source_manifest_ref:
        raise ValueError("Recurring workload manifest has no source manifest ref")
    source_manifest = read_json(source_manifest_ref)
    if not isinstance(source_manifest, dict):
        raise ValueError("Recurring workload source manifest must be an object")
    for field in ("source_repository", "source_commit"):
        if source_manifest.get(field) != manifest.get(field):
            raise ValueError(
                f"Recurring workload {field} disagrees with its source manifest"
            )

    batches = _validate_batches(
        read_parquet_rows(str(table_refs["sandbox_benchmark_batches"])),
        prices,
    )
    replicates = _validate_replicates(
        read_parquet_rows(str(table_refs["sandbox_benchmark_replicates"])),
        prices,
        batches,
    )
    phases = _validate_phases(
        read_parquet_rows(str(table_refs["sandbox_benchmark_phases"])),
        replicates,
    )
    run_metadata = _validate_run_metadata(
        read_parquet_rows(str(table_refs["sandbox_benchmark_run_metadata"])),
        batches,
        replicates,
    )
    _validate_source_manifest(source_manifest, batches)

    canonical_keys = {
        (str(row["series_id"]), str(row["benchmark_run_id"]))
        for row in canonical_payload.get("batch_rows", [])
    }
    operational_keys = {
        (str(row["series_id"]), str(row["benchmark_run_id"])) for row in batches
    }
    missing = canonical_keys - operational_keys
    if missing:
        raise ValueError(
            "Recurring workload generation would drop reviewed history: "
            f"{sorted(missing)[:5]}"
        )

    payload = {
        **canonical_payload,
        "retrieved_at": manifest.get("dataset_observed_at"),
        "source_repository": manifest.get("source_repository"),
        "source_commit": manifest.get("source_commit"),
        "batch_rows": batches,
        "replicate_rows": replicates,
        "phase_rows": phases,
        "run_metadata": run_metadata,
    }
    return (
        payload,
        source_manifest,
        batches,
        replicates,
        phases,
        run_metadata,
    )
