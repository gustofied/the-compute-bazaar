"""Validate retained StarSling workload and cost evidence."""

from __future__ import annotations

from .evidence_schema import (
    BATCH_FIELDS,
    BENCHMARK_EVIDENCE,
    PHASE_FIELDS,
    PRICE_FIELDS,
    RATE_METERING,
    REPLICATE_FIELDS,
    RUNTIME_PRICE_SERIES,
    RUN_METADATA_FIELDS,
    SOURCE_MANIFEST,
    TARGET_SHAPE,
    WORKLOAD_COST_COHORT,
    WORKLOAD_COST_INPUTS,
)

import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from the_compute_bazaar.prices.storage import (
    write_bytes,
)


def validate_evidence(
    *,
    price_path: Path = WORKLOAD_COST_INPUTS,
    benchmark_path: Path = BENCHMARK_EVIDENCE,
    source_manifest_path: Path = SOURCE_MANIFEST,
) -> dict[str, Any]:
    """Validate formulas, matching rules, uniqueness, shape, and source retention."""
    prices_payload = _read_local_json(price_path)
    benchmarks_payload = _read_local_json(benchmark_path)
    source_manifest = _read_local_json(source_manifest_path)
    _require_schema(
        prices_payload,
        "sandbox_workload_cost_input_v2",
        price_path,
    )
    _require_schema(
        benchmarks_payload,
        "sandbox_benchmark_observation_v2",
        benchmark_path,
    )
    _require_schema(
        source_manifest,
        "sandbox_source_manifest_v1",
        source_manifest_path,
    )

    prices = _validate_prices(prices_payload.get("rows"))
    batches = _validate_batches(benchmarks_payload.get("batch_rows"), prices)
    replicates = _validate_replicates(
        benchmarks_payload.get("replicate_rows"),
        prices,
        batches,
    )
    phases = _validate_phases(
        benchmarks_payload.get("phase_rows"),
        replicates,
    )
    run_metadata = _validate_run_metadata(
        benchmarks_payload.get("run_metadata"),
        batches,
        replicates,
    )
    _validate_source_manifest(source_manifest, batches)

    return _evidence_summary(
        prices=prices,
        batches=batches,
        replicates=replicates,
        phases=phases,
        run_metadata=run_metadata,
        source_manifest=source_manifest,
    )


def _evidence_summary(
    *,
    prices: list[dict[str, Any]],
    batches: list[dict[str, Any]],
    replicates: list[dict[str, Any]],
    phases: list[dict[str, Any]],
    run_metadata: list[dict[str, Any]],
    source_manifest: dict[str, Any],
) -> dict[str, Any]:
    return {
        "price_input_count": len(prices),
        "priced_service_count": len({row["series_id"] for row in prices}),
        "benchmark_batch_count": len(batches),
        "benchmark_replicate_count": len(replicates),
        "benchmark_phase_count": len(phases),
        "benchmark_service_count": len({row["series_id"] for row in batches}),
        "benchmark_run_count": len({row["benchmark_run_id"] for row in batches}),
        "benchmark_calendar_day_count": len({row["observed_date"] for row in batches}),
        "benchmark_methodology_count": len(
            {row["methodology_id"] for row in run_metadata}
        ),
        "latest_replicate_run_id": max(
            run_metadata,
            key=lambda row: row["generated_at"],
        )["benchmark_run_id"],
        "priced_services": sorted(
            {
                row["series_id"]
                for row in prices
                if row["workload_cost_cohort"] == WORKLOAD_COST_COHORT
            }
        ),
        "source_file_count": len(source_manifest["files"]),
    }


def _validate_prices(raw_rows: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_rows, list) or not raw_rows:
        raise ValueError("Hourly-price evidence must contain a non-empty rows list")
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for position, raw in enumerate(raw_rows):
        row = _strict_row(raw, PRICE_FIELDS, f"hourly price row {position}")
        _parse_date(row["observed_date"], f"hourly price row {position}")
        key = (row["series_id"], row["observed_date"], row["source_url"])
        if key in seen:
            raise ValueError(f"Duplicate hourly-price observation: {key}")
        seen.add(key)
        if not str(row["source_url"]).startswith(("https://", "http://")):
            raise ValueError(f"Missing source URL for hourly-price observation {key}")
        expected = Decimal(str(row["processor_quantity"])) * Decimal(
            str(row["processor_rate_usd_per_unit_hour"])
        ) + Decimal(str(row["memory_gib"])) * Decimal(
            str(row["memory_rate_usd_per_gib_hour"])
        )
        observed = Decimal(str(row["price_usd_per_hour"]))
        if abs(expected - observed) > Decimal("0.000001"):
            raise ValueError(
                f"Bad hourly-price formula for {row['series_id']} on "
                f"{row['observed_date']}: expected {expected}, found {observed}"
            )
        try:
            metering = RATE_METERING[str(row["series_id"])]
        except KeyError as error:
            raise ValueError(
                f"Missing rate-metering semantics for {row['series_id']}"
            ) from error
        rows.append({**row, **metering})
    return rows


def _validate_batches(
    raw_rows: Any,
    prices: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(raw_rows, list) or not raw_rows:
        raise ValueError("Benchmark evidence must contain non-empty batch_rows")
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    for position, raw in enumerate(raw_rows):
        row = _strict_row(raw, BATCH_FIELDS, f"benchmark batch {position}")
        _parse_date(row["observed_date"], f"benchmark batch {position}")
        _parse_timestamp(row["generated_at"], f"benchmark batch {position}")
        key = (
            row["series_id"],
            row["generated_at"],
            row["benchmark_run_id"],
        )
        if key in seen:
            raise ValueError(f"Duplicate benchmark batch: {key}")
        seen.add(key)
        _validate_workload_cost_row(row, prices, key)
        if row["observation_level"] != "provider_batch_summary":
            raise ValueError(f"Unexpected batch observation level for {key}")
        if row["runtime_basis"] != "sum_of_published_task_means":
            raise ValueError(f"Unexpected batch runtime basis for {key}")
        if int(row["replicate_count"]) < 1:
            raise ValueError(f"Invalid replicate count for {key}")
        if bool(row["replicate_data_available"]) and int(row["replicate_count"]) < 2:
            raise ValueError(f"Indexed replicate batch is too small for {key}")
        rows.append(row)
    return rows


def _validate_replicates(
    raw_rows: Any,
    prices: list[dict[str, Any]],
    batches: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(raw_rows, list) or not raw_rows:
        raise ValueError("Benchmark evidence must contain non-empty replicate_rows")
    batch_keys = {(row["series_id"], row["benchmark_run_id"]): row for row in batches}
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int]] = set()
    for position, raw in enumerate(raw_rows):
        row = _strict_row(raw, REPLICATE_FIELDS, f"benchmark replicate {position}")
        _parse_date(row["observed_date"], f"benchmark replicate {position}")
        _parse_timestamp(row["generated_at"], f"benchmark replicate {position}")
        key = (
            row["series_id"],
            row["benchmark_run_id"],
            int(row["replicate_index"]),
        )
        if key in seen:
            raise ValueError(f"Duplicate benchmark replicate: {key}")
        seen.add(key)
        _validate_workload_cost_row(row, prices, key)
        if row["observation_level"] != "aligned_job_replicate":
            raise ValueError(f"Unexpected replicate observation level for {key}")
        if row["runtime_basis"] != "sum_of_ten_task_samples_with_same_replicate_index":
            raise ValueError(f"Unexpected replicate runtime basis for {key}")
        if int(row["task_count"]) != 10:
            raise ValueError(f"Expected ten phases for replicate {key}")
        batch = batch_keys.get((row["series_id"], row["benchmark_run_id"]))
        if batch is None:
            raise ValueError(f"Replicate has no retained batch: {key}")
        for field in (
            "methodology_id",
            "source_run_sha",
            "task_signature",
            "workload_app_version",
        ):
            if row[field] != batch[field]:
                raise ValueError(f"Replicate {key} disagrees with its batch on {field}")
        rows.append(row)

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(
            (row["series_id"], row["benchmark_run_id"]),
            [],
        ).append(row)
    for key, batch in batch_keys.items():
        if not batch["replicate_data_available"]:
            continue
        group = grouped.get(key, [])
        if len(group) != int(batch["replicate_count"]):
            raise ValueError(
                f"Replicate count does not match batch {key}: "
                f"{len(group)} != {batch['replicate_count']}"
            )
        mean_runtime = sum(float(row["runtime_seconds"]) for row in group) / len(group)
        if abs(mean_runtime - float(batch["runtime_seconds"])) > 0.000001:
            raise ValueError(f"Replicate mean does not reproduce batch runtime {key}")
    return rows


def _validate_phases(
    raw_rows: Any,
    replicates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(raw_rows, list) or not raw_rows:
        raise ValueError("Benchmark evidence must contain non-empty phase_rows")
    replicate_keys = {
        (
            row["series_id"],
            row["benchmark_run_id"],
            int(row["replicate_index"]),
        ): row
        for row in replicates
    }
    grouped: dict[tuple[str, str, int], list[dict[str, Any]]] = {}
    seen: set[tuple[str, str, int, str]] = set()
    rows: list[dict[str, Any]] = []
    for position, raw in enumerate(raw_rows):
        row = _strict_row(raw, PHASE_FIELDS, f"benchmark phase {position}")
        key = (
            row["series_id"],
            row["benchmark_run_id"],
            int(row["replicate_index"]),
            row["task_id"],
        )
        if key in seen:
            raise ValueError(f"Duplicate benchmark phase: {key}")
        seen.add(key)
        replicate_key = key[:3]
        replicate = replicate_keys.get(replicate_key)
        if replicate is None:
            raise ValueError(f"Phase has no retained replicate: {key}")
        if not 1 <= int(row["task_order"]) <= 10:
            raise ValueError(f"Invalid task order for phase {key}")
        if float(row["runtime_seconds"]) <= 0:
            raise ValueError(f"Invalid phase runtime for {key}")
        for field in (
            "methodology_id",
            "source_run_sha",
            "task_signature",
            "workload_app_version",
        ):
            if row[field] != replicate[field]:
                raise ValueError(f"Phase {key} disagrees with its replicate on {field}")
        grouped.setdefault(replicate_key, []).append(row)
        rows.append(row)
    for key, replicate in replicate_keys.items():
        phases = grouped.get(key, [])
        if len(phases) != 10 or {int(row["task_order"]) for row in phases} != set(
            range(1, 11)
        ):
            raise ValueError(f"Replicate {key} does not contain ten unique phases")
        total = sum(float(row["runtime_seconds"]) for row in phases)
        if abs(total - float(replicate["runtime_seconds"])) > 0.000001:
            raise ValueError(f"Phase total does not reproduce replicate runtime {key}")
    return rows


def _validate_run_metadata(
    raw_rows: Any,
    batches: list[dict[str, Any]],
    replicates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(raw_rows, list) or not raw_rows:
        raise ValueError("Benchmark evidence must contain non-empty run_metadata")
    batch_runs: dict[str, list[dict[str, Any]]] = {}
    replicate_runs = {row["benchmark_run_id"] for row in replicates}
    for row in batches:
        batch_runs.setdefault(row["benchmark_run_id"], []).append(row)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for position, raw in enumerate(raw_rows):
        row = _strict_row(raw, RUN_METADATA_FIELDS, f"run metadata {position}")
        run_id = row["benchmark_run_id"]
        if run_id in seen:
            raise ValueError(f"Duplicate run metadata: {run_id}")
        seen.add(run_id)
        _parse_timestamp(row["generated_at"], f"run metadata {position}")
        members = batch_runs.get(run_id)
        if not members:
            raise ValueError(f"Run metadata has no retained batch: {run_id}")
        if int(row["provider_result_count"]) != len(members):
            raise ValueError(f"Wrong provider count in run metadata {run_id}")
        if bool(row["replicate_indexed"]) != (run_id in replicate_runs):
            raise ValueError(f"Wrong replicate-indexed status in run metadata {run_id}")
        for member in members:
            for field in (
                "methodology_id",
                "source_run_sha",
                "task_signature",
                "workload_app_version",
            ):
                if row[field] != member[field]:
                    raise ValueError(
                        f"Run metadata {run_id} disagrees with batch on {field}"
                    )
        rows.append(row)
    if seen != set(batch_runs):
        raise ValueError("Run metadata does not cover every retained batch run")
    return rows


def _validate_workload_cost_row(
    row: dict[str, Any],
    prices: list[dict[str, Any]],
    key: tuple[Any, ...],
) -> None:
    shape = {
        "vcpus": int(row["vcpus"]),
        "memory_gib": int(row["memory_gib"]),
        "disk_gb": int(row["disk_gb"]),
    }
    if shape != TARGET_SHAPE:
        raise ValueError(
            f"Incompatible machine shape in {row['benchmark_run_id']}: {shape}"
        )
    if int(row["job_parts"]) != 10:
        raise ValueError(
            f"Expected ten job parts in {row['benchmark_run_id']} "
            f"for {row['series_id']}"
        )
    if row["price_scope"] != "processor_and_memory_only":
        raise ValueError(f"Unexpected price scope in benchmark result {key}")
    if row["cost_basis"] != "public_rate_card_unmetered":
        raise ValueError(f"Unexpected cost basis in benchmark result {key}")
    if row["lifecycle_included"] is not False:
        raise ValueError(f"Lifecycle must remain explicitly excluded for {key}")
    if float(row["runtime_seconds"]) <= 0:
        raise ValueError(f"Invalid workload runtime for {key}")
    if int(row["workload_gap_count"]) < 0:
        raise ValueError(f"Invalid workload gap count for {key}")
    if len(str(row["source_run_sha"])) != 40:
        raise ValueError(f"Missing source run SHA for {key}")
    if len(str(row["task_signature"])) != 64:
        raise ValueError(f"Missing task signature for {key}")
    if len(str(row["workload_app_version"])) != 40:
        raise ValueError(f"Missing workload version for {key}")
    if not str(row["methodology_id"]).startswith("starsling-better-auth-"):
        raise ValueError(f"Invalid methodology ID for {key}")
    if not str(row["benchmark_source_url"]).startswith(
        "https://github.com/starslingdev/hpc-sandbox-benchmarks/"
    ):
        raise ValueError(f"Missing benchmark source URL for {key}")
    if (
        row["observed_vcpus"] is not None
        and abs(float(row["observed_vcpus"]) - TARGET_SHAPE["vcpus"]) > 0.01
    ):
        raise ValueError(f"Observed vCPU mismatch for {key}")
    if (
        row["observed_memory_gib"] is not None
        and abs(float(row["observed_memory_gib"]) - TARGET_SHAPE["memory_gib"])
        > TARGET_SHAPE["memory_gib"] * 0.1
    ):
        raise ValueError(f"Observed memory mismatch for {key}")

    expected_cost = (
        Decimal(str(row["runtime_seconds"]))
        * Decimal(str(row["hourly_price_usd"]))
        / Decimal("3600")
    )
    observed_cost = Decimal(str(row["estimated_cost_usd"]))
    if abs(expected_cost - observed_cost) > Decimal("0.000000001"):
        raise ValueError(
            f"Bad workload cost for {row['series_id']} on "
            f"{row['generated_at']}: expected {expected_cost}, "
            f"found {observed_cost}"
        )
    price_series = RUNTIME_PRICE_SERIES.get(row["series_id"])
    if price_series is None:
        raise ValueError(f"Unknown benchmark service {row['series_id']!r}")
    candidates = sorted(
        (
            price
            for price in prices
            if price["series_id"] == price_series
            and price["observed_date"] <= row["observed_date"]
        ),
        key=lambda price: price["observed_date"],
    )
    if not candidates:
        raise ValueError(f"No {price_series} price at or before {row['observed_date']}")
    price = candidates[-1]
    if row["price_date"] != price["observed_date"]:
        raise ValueError(f"Wrong price date retained for benchmark result {key}")
    if row["price_source_url"] != price["source_url"]:
        raise ValueError(f"Wrong price source retained for benchmark result {key}")
    if abs(
        Decimal(str(row["hourly_price_usd"]))
        - Decimal(str(price["price_usd_per_hour"]))
    ) > Decimal("0.000001"):
        raise ValueError(f"Wrong hourly price retained for benchmark result {key}")


def _validate_source_manifest(
    manifest: dict[str, Any],
    benchmarks: list[dict[str, Any]],
) -> None:
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("Source manifest must contain files")
    paths: set[str] = set()
    for position, raw in enumerate(files):
        row = _strict_row(
            raw,
            {"path", "source_url", "sha256", "size_bytes"},
            f"source manifest row {position}",
        )
        if row["path"] in paths:
            raise ValueError(f"Duplicate source-manifest path: {row['path']}")
        paths.add(row["path"])
        if len(str(row["sha256"])) != 64:
            raise ValueError(f"Invalid SHA-256 for {row['path']}")
        if int(row["size_bytes"]) < 1:
            raise ValueError(f"Invalid source size for {row['path']}")
    for run_id in {row["benchmark_run_id"] for row in benchmarks}:
        expected_path = f"data/dataset/runs/{run_id}.json"
        if expected_path not in paths:
            raise ValueError(f"Source manifest does not retain run {run_id}")


def _read_local_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _require_schema(payload: dict[str, Any], expected: str, path: Path) -> None:
    observed = payload.get("schema_version")
    if observed != expected:
        raise ValueError(
            f"Schema drift in {path}: expected {expected!r}, found {observed!r}"
        )


def _strict_row(raw: Any, fields: set[str], label: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"{label} is not an object")
    observed = set(raw)
    missing = fields - observed
    extra = observed - fields
    if missing or extra:
        details = []
        if missing:
            details.append(f"missing {', '.join(sorted(missing))}")
        if extra:
            details.append(f"unexpected {', '.join(sorted(extra))}")
        raise ValueError(f"Schema drift in {label}: {'; '.join(details)}")
    return dict(raw)


def _parse_date(value: Any, label: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"Invalid date in {label}: {value!r}") from exc


def _parse_timestamp(value: Any, label: str) -> datetime:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Invalid timestamp in {label}: {value!r}") from exc


def write_source_capture(ref: str, data: bytes) -> str:
    """Write immutable source bytes without altering their payload."""
    return write_bytes(ref, data, content_type="application/octet-stream")
