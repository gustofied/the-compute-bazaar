"""Canonical schema declarations for retained StarSling evidence."""

from __future__ import annotations

from pathlib import Path


EVIDENCE_ROOT = Path(__file__).with_name("evidence")

WORKLOAD_COST_INPUTS = EVIDENCE_ROOT / "workload-cost-inputs.json"

BENCHMARK_EVIDENCE = EVIDENCE_ROOT / "benchmark-observations.json"

SOURCE_MANIFEST = EVIDENCE_ROOT / "source-manifest.json"

TARGET_SHAPE = {"vcpus": 4, "memory_gib": 8, "disk_gb": 40}

WORKLOAD_COST_COHORT = "workload-cost-input"

RUNTIME_PRICE_SERIES = {
    "blaxel": "blaxel",
    "daytona-vm": "daytona",
    "e2b": "e2b",
    "modal-gvisor": "modal",
    "modal-vm": "modal",
    "novita": "novita",
}

RATE_METERING = {
    "beam": {
        "processor_meter": "reserved_capacity",
        "memory_meter": "reserved_capacity",
        "billing_basis_label": "physical cores and memory while running",
    },
    "blaxel": {
        "processor_meter": "memory_coupled",
        "memory_meter": "active_runtime",
        "billing_basis_label": "active runtime, priced by allocated memory",
    },
    "daytona": {
        "processor_meter": "reserved_capacity",
        "memory_meter": "reserved_capacity",
        "billing_basis_label": "reserved CPU and memory while running",
    },
    "e2b": {
        "processor_meter": "reserved_capacity",
        "memory_meter": "reserved_capacity",
        "billing_basis_label": "reserved CPU and memory while running",
    },
    "fly-sprites": {
        "processor_meter": "actual_usage",
        "memory_meter": "actual_usage",
        "billing_basis_label": "actual CPU and memory use",
    },
    "freestyle": {
        "processor_meter": "reserved_capacity",
        "memory_meter": "reserved_capacity",
        "billing_basis_label": "VM CPU and memory while running",
    },
    "modal": {
        "processor_meter": "max_requested_or_actual",
        "memory_meter": "max_requested_or_actual",
        "billing_basis_label": "higher of requested or actual use",
    },
    "novita": {
        "processor_meter": "reserved_capacity",
        "memory_meter": "reserved_capacity",
        "billing_basis_label": "allocated CPU and memory while running",
    },
    "runloop": {
        "processor_meter": "reserved_capacity",
        "memory_meter": "reserved_capacity",
        "billing_basis_label": "devbox CPU and memory while active",
    },
    "sailboxes": {
        "processor_meter": "actual_usage",
        "memory_meter": "actual_usage",
        "billing_basis_label": "actual CPU and memory use",
    },
    "vercel": {
        "processor_meter": "active_usage",
        "memory_meter": "reserved_capacity",
        "billing_basis_label": "active CPU and provisioned memory",
    },
}

COST_INPUT_FIELDS = {
    "series_order",
    "point_order",
    "series_id",
    "series_label",
    "observed_date",
    "price_usd_per_hour",
    "processor_quantity",
    "processor_unit",
    "processor_rate_usd_per_unit_hour",
    "memory_gib",
    "memory_rate_usd_per_gib_hour",
    "date_role",
    "change_precision",
    "source_role",
    "workload_cost_eligible",
    "workload_cost_cohort",
    "evidence_class",
    "source_label",
    "source_url",
    "note",
    "color",
}

BATCH_FIELDS = {
    "series_order",
    "point_order",
    "series_id",
    "series_label",
    "observed_date",
    "generated_at",
    "runtime_seconds",
    "hourly_price_usd",
    "estimated_cost_usd",
    "price_scope",
    "vcpus",
    "memory_gib",
    "disk_gb",
    "observed_vcpus",
    "observed_memory_gib",
    "observed_disk_gb",
    "cpu_model",
    "virtualization",
    "country",
    "region",
    "city",
    "egress_asn",
    "job_parts",
    "benchmark_run_id",
    "source_run_sha",
    "workload_app_version",
    "task_signature",
    "methodology_id",
    "benchmark_source_url",
    "price_date",
    "price_source_url",
    "cost_basis",
    "lifecycle_included",
    "workload_gap_count",
    "replicate_count",
    "replicate_data_available",
    "observation_level",
    "runtime_basis",
    "note",
    "color",
}

REPLICATE_FIELDS = {
    "series_order",
    "series_id",
    "series_label",
    "observed_date",
    "generated_at",
    "runtime_seconds",
    "hourly_price_usd",
    "estimated_cost_usd",
    "price_scope",
    "vcpus",
    "memory_gib",
    "disk_gb",
    "observed_vcpus",
    "observed_memory_gib",
    "observed_disk_gb",
    "cpu_model",
    "virtualization",
    "country",
    "region",
    "city",
    "egress_asn",
    "job_parts",
    "benchmark_run_id",
    "source_run_sha",
    "workload_app_version",
    "task_signature",
    "methodology_id",
    "benchmark_source_url",
    "price_date",
    "price_source_url",
    "cost_basis",
    "lifecycle_included",
    "workload_gap_count",
    "color",
    "replicate_index",
    "task_count",
    "observation_level",
    "runtime_basis",
}

PHASE_FIELDS = {
    "series_order",
    "series_id",
    "series_label",
    "observed_date",
    "generated_at",
    "benchmark_run_id",
    "source_run_sha",
    "methodology_id",
    "workload_app_version",
    "task_signature",
    "replicate_index",
    "task_order",
    "task_id",
    "task_label",
    "runtime_seconds",
    "benchmark_source_url",
    "color",
}

RUN_METADATA_FIELDS = {
    "benchmark_run_id",
    "generated_at",
    "source_run_sha",
    "methodology_id",
    "workload_app_version",
    "task_signature",
    "target_vcpus",
    "target_memory_gib",
    "target_disk_gb",
    "task_count",
    "provider_result_count",
    "replicate_indexed",
    "runtime_basis",
    "lifecycle_included",
    "benchmark_source_url",
}
