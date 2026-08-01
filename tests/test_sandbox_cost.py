import copy
import json
import statistics
import tempfile
import unittest
from pathlib import Path

from the_compute_bazaar.prices.storage import write_parquet_rows
from the_compute_bazaar.sandbox_cost.pipeline import (
    BENCHMARK_EVIDENCE,
    PRICE_EVIDENCE,
    SOURCE_MANIFEST,
    UTILIZATION_EVIDENCE,
    _read_local_json,
    build_sandbox_cost,
    check_public_payload_freshness,
    query_sandbox_gold,
    validate_evidence,
)
from the_compute_bazaar.sandbox_cost.refresh import (
    TASK_ARGUMENTS,
    WORKLOAD_APP_VERSION,
    _merge_historical_rows,
    _parse_index,
    _publish_operational_benchmark,
    extract_benchmark_evidence,
    extract_benchmark_rows,
)


class PublicFreshnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = {
            "manifest": {
                "built_at": "2026-07-25T10:00:00+00:00",
                "vm_capacity_source_manifest": {
                    "run_id": "vm-capacity-20260725T100000Z",
                    "status": "ok",
                },
                "vm_discovery_source_manifest": {
                    "run_id": "vm-discovery-20260725T100000Z",
                    "status": "ok",
                },
            },
            "vm_capacity": {
                "observed_market_rate": [{"observed_at": "2026-07-25T10:00:00"}]
            },
        }

    def test_public_freshness_accepts_current_complete_snapshot(self) -> None:
        result = check_public_payload_freshness(
            self.payload,
            now="2026-07-25T11:00:00+00:00",
            max_age_hours=2.5,
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["problems"], [])

    def test_public_freshness_rejects_stale_or_partial_snapshot(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["manifest"]["vm_discovery_source_manifest"]["status"] = "warning"
        result = check_public_payload_freshness(
            payload,
            now="2026-07-25T13:00:01+00:00",
            max_age_hours=2.5,
        )

        self.assertEqual(result["status"], "fail")
        self.assertEqual(
            result["problems"],
            [
                "public_snapshot_stale",
                "vm_benchmark_stale",
                "partial_vm_source_check",
            ],
        )


class SandboxCostEvidenceTests(unittest.TestCase):
    def test_canonical_evidence_counts_and_shape(self) -> None:
        summary = validate_evidence()

        self.assertEqual(summary["price_observation_count"], 33)
        self.assertEqual(summary["price_service_count"], 11)
        self.assertEqual(summary["benchmark_batch_count"], 62)
        self.assertEqual(summary["benchmark_replicate_count"], 353)
        self.assertEqual(summary["benchmark_phase_count"], 3530)
        self.assertEqual(summary["benchmark_service_count"], 6)
        self.assertEqual(summary["benchmark_run_count"], 11)
        self.assertEqual(summary["benchmark_calendar_day_count"], 8)
        self.assertEqual(summary["benchmark_methodology_count"], 10)
        self.assertEqual(summary["latest_replicate_run_id"], "30655876610")
        self.assertEqual(len(summary["fixed_members"]), 8)
        self.assertEqual(summary["utilization_metric_count"], 8)
        self.assertEqual(summary["utilization_public_stage_count"], 5)

    def test_duplicate_hourly_observation_is_rejected(self) -> None:
        prices = _read_local_json(PRICE_EVIDENCE)
        prices["rows"].append(copy.deepcopy(prices["rows"][0]))

        with tempfile.TemporaryDirectory() as tmpdir:
            price_path = Path(tmpdir) / "prices.json"
            price_path.write_text(json.dumps(prices), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Duplicate hourly-price"):
                validate_evidence(price_path=price_path)

    def test_incompatible_benchmark_shape_is_rejected(self) -> None:
        benchmarks = _read_local_json(BENCHMARK_EVIDENCE)
        benchmarks["batch_rows"][0]["vcpus"] = 2

        with tempfile.TemporaryDirectory() as tmpdir:
            benchmark_path = Path(tmpdir) / "benchmark.json"
            benchmark_path.write_text(json.dumps(benchmarks), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Incompatible machine shape"):
                validate_evidence(benchmark_path=benchmark_path)

    def test_missing_run_source_is_rejected(self) -> None:
        source_manifest = _read_local_json(SOURCE_MANIFEST)
        source_manifest["files"] = [
            row
            for row in source_manifest["files"]
            if "29692210375.json" not in row["path"]
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "source-manifest.json"
            manifest_path.write_text(
                json.dumps(source_manifest),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "does not retain run"):
                validate_evidence(source_manifest_path=manifest_path)

    def test_benchmark_index_schema_drift_is_rejected(self) -> None:
        payload = {
            "schemaVersion": "1",
            "runs": [
                {
                    "runId": "1",
                    "generatedAt": "2026-07-24T00:00:00Z",
                    "path": "runs/1.json",
                    "newField": True,
                }
            ],
        }

        with self.assertRaisesRegex(ValueError, "Schema drift"):
            _parse_index(json.dumps(payload).encode())

    def test_ambiguous_utilization_field_name_is_rejected(self) -> None:
        methodology = _read_local_json(UTILIZATION_EVIDENCE)
        methodology["rows"][0]["recommended_field_name"] = "utilization"

        with tempfile.TemporaryDirectory() as tmpdir:
            methodology_path = Path(tmpdir) / "utilization.json"
            methodology_path.write_text(
                json.dumps(methodology),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "ambiguous field name"):
                validate_evidence(utilization_path=methodology_path)


class SandboxCostPipelineTests(unittest.TestCase):
    def test_operational_workload_rejects_a_retained_result_rewrite(
        self,
    ) -> None:
        benchmarks = _read_local_json(BENCHMARK_EVIDENCE)
        prices = _read_local_json(PRICE_EVIDENCE)["rows"]
        source_manifest = _read_local_json(SOURCE_MANIFEST)
        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = str(Path(tmpdir) / "lake")
            _publish_operational_benchmark(
                output_root=output_root,
                source_repository=source_manifest["source_repository"],
                source_commit=source_manifest["source_commit"],
                checked_at="2026-07-26T06:30:00+00:00",
                refresh_id="workload-refresh-20260726T063000000000Z",
                source_manifest=source_manifest,
                source_manifest_ref=str(Path(tmpdir) / "raw" / "first.json"),
                prices=prices,
                batch_rows=benchmarks["batch_rows"],
                replicate_rows=benchmarks["replicate_rows"],
                phase_rows=benchmarks["phase_rows"],
                run_metadata=benchmarks["run_metadata"],
            )
            changed = copy.deepcopy(benchmarks["batch_rows"])
            changed[0]["runtime_seconds"] += 1
            changed[0]["estimated_cost_usd"] = round(
                changed[0]["runtime_seconds"] * changed[0]["hourly_price_usd"] / 3600,
                9,
            )

            with self.assertRaisesRegex(
                ValueError,
                "Source changed an existing benchmark result",
            ):
                _publish_operational_benchmark(
                    output_root=output_root,
                    source_repository=source_manifest["source_repository"],
                    source_commit=source_manifest["source_commit"],
                    checked_at="2026-07-27T06:30:00+00:00",
                    refresh_id="workload-refresh-20260727T063000000000Z",
                    source_manifest=source_manifest,
                    source_manifest_ref=str(Path(tmpdir) / "raw" / "second.json"),
                    prices=prices,
                    batch_rows=changed,
                    replicate_rows=benchmarks["replicate_rows"],
                    phase_rows=benchmarks["phase_rows"],
                    run_metadata=benchmarks["run_metadata"],
                )

    def test_operational_workload_generation_is_idempotent_and_used_by_gold(
        self,
    ) -> None:
        benchmarks = _read_local_json(BENCHMARK_EVIDENCE)
        prices = _read_local_json(PRICE_EVIDENCE)["rows"]
        source_manifest = _read_local_json(SOURCE_MANIFEST)
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            first = _publish_operational_benchmark(
                output_root=str(root / "lake"),
                source_repository=source_manifest["source_repository"],
                source_commit=source_manifest["source_commit"],
                checked_at="2026-07-26T06:30:00+00:00",
                refresh_id="workload-refresh-20260726T063000000000Z",
                source_manifest=source_manifest,
                source_manifest_ref=str(root / "raw" / "first.json"),
                prices=prices,
                batch_rows=benchmarks["batch_rows"],
                replicate_rows=benchmarks["replicate_rows"],
                phase_rows=benchmarks["phase_rows"],
                run_metadata=benchmarks["run_metadata"],
            )
            second = _publish_operational_benchmark(
                output_root=str(root / "lake"),
                source_repository=source_manifest["source_repository"],
                source_commit=source_manifest["source_commit"],
                checked_at="2026-07-27T06:30:00+00:00",
                refresh_id="workload-refresh-20260727T063000000000Z",
                source_manifest=source_manifest,
                source_manifest_ref=str(root / "raw" / "second.json"),
                prices=prices,
                batch_rows=benchmarks["batch_rows"],
                replicate_rows=benchmarks["replicate_rows"],
                phase_rows=benchmarks["phase_rows"],
                run_metadata=benchmarks["run_metadata"],
            )
            build = build_sandbox_cost(output_root=str(root / "lake"))
            latest = json.loads(
                (
                    root
                    / "lake"
                    / "silver"
                    / "_manifests"
                    / "workload_benchmark"
                    / "latest.json"
                ).read_text()
            )
            polls = list(
                (
                    root
                    / "lake"
                    / "silver"
                    / "_manifests"
                    / "workload_benchmark"
                    / "polls"
                ).rglob("*.json")
            )

        self.assertEqual(first["generation_id"], second["generation_id"])
        self.assertEqual(first["table_refs"], second["table_refs"])
        self.assertEqual(len(polls), 2)
        self.assertEqual(
            latest["latest_refresh_id"],
            "workload-refresh-20260727T063000000000Z",
        )
        self.assertEqual(
            build.row_counts["sandbox_workload_latest_replicates"],
            72,
        )
        self.assertEqual(
            build.row_counts["sandbox_workload_latest_phases"],
            720,
        )

    def test_build_is_deterministic_and_public_payload_retains_all_runs(self) -> None:
        expected_manifest_date = _read_local_json(SOURCE_MANIFEST)["retrieved_at"][:10]
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            gpu_history = root / "benchmark-history.json"
            gpu_history.write_text(
                json.dumps(
                    {
                        "manifest": {
                            "dashboard_exported_at": "2026-07-24T12:00:00Z",
                            "dashboard_output_root": "s3://private-bucket/dashboard",
                            "observed_at": "2026-07-24T12:00:00Z",
                            "run_id": "gold-test",
                            "source_run_ids": {"vast": "private-run"},
                        },
                        "rows": [
                            _gpu_row("2026-07-22T23:00:00Z", 2.75, 2),
                            _gpu_row("2026-07-23T23:00:00Z", 2.5, 12),
                            _gpu_row("2026-07-24T12:00:00Z", 2.25, 14),
                        ],
                    }
                ),
                encoding="utf-8",
            )
            output_root = str(root / "lake")
            dashboard_root = str(root / "dashboard")

            first = build_sandbox_cost(
                output_root=output_root,
                dashboard_output_root=dashboard_root,
                gpu_history_ref=str(gpu_history),
            )
            second = build_sandbox_cost(
                output_root=output_root,
                dashboard_output_root=dashboard_root,
                gpu_history_ref=str(gpu_history),
            )
            public = json.loads((root / "dashboard" / "sandbox-cost.json").read_text())
            rate_card = json.loads(
                (root / "dashboard" / "sandbox" / "rates.json").read_text()
            )
            workload_card = json.loads(
                (root / "dashboard" / "sandbox" / "workload.json").read_text()
            )
            relative_card = json.loads(
                (root / "dashboard" / "sandbox" / "relative.json").read_text()
            )

        self.assertEqual(first.build_id, second.build_id)
        self.assertIn(
            f"_manifests/sandbox_cost/date={expected_manifest_date}/"
            f"build_id={first.build_id}.json",
            first.manifest_ref,
        )
        self.assertTrue(
            all(
                f"gold/generations/build_id={first.build_id}/" in ref
                for ref in first.table_refs.values()
            )
        )
        self.assertEqual(first.row_counts["sandbox_hourly_price_series"], 33)
        self.assertEqual(first.row_counts["sandbox_price_events"], 10)
        self.assertEqual(first.row_counts["sandbox_current_rates"], 11)
        self.assertEqual(first.row_counts["sandbox_fixed_rate"], 4)
        self.assertEqual(first.row_counts["sandbox_workload_batch_history"], 62)
        self.assertEqual(first.row_counts["sandbox_workload_run_history"], 11)
        self.assertEqual(
            first.row_counts["sandbox_workload_latest_replicates"],
            72,
        )
        self.assertEqual(
            first.row_counts["sandbox_workload_latest_phases"],
            720,
        )
        self.assertEqual(
            first.row_counts["sandbox_workload_phase_summary"],
            60,
        )
        self.assertEqual(
            first.row_counts["sandbox_workload_service_summary"],
            6,
        )
        self.assertEqual(first.row_counts["gpu_h100_daily_coverage"], 3)
        self.assertEqual(first.row_counts["gpu_h100_eligible_history"], 2)
        self.assertEqual(first.row_counts["sandbox_gpu_cpu_common_start"], 2)
        self.assertEqual(
            first.row_counts["compute_utilization_public_ladder"],
            5,
        )
        self.assertEqual(public["manifest"]["manifest_version"], "sandbox_cost_gold_v5")
        self.assertEqual(rate_card["schema_version"], "compute_bazaar_card_v1")
        self.assertEqual(rate_card["card_type"], "compute_rate_market")
        self.assertEqual(workload_card["schema_version"], "compute_bazaar_card_v1")
        self.assertEqual(workload_card["card_type"], "sandbox_workload")
        self.assertEqual(relative_card["schema_version"], "compute_bazaar_card_v1")
        self.assertEqual(
            relative_card["card_type"],
            "compute_relative_prices",
        )
        self.assertEqual(relative_card["status"], "unavailable")
        self.assertEqual(
            workload_card["coverage"]["latest_replicate_count"],
            72,
        )
        self.assertEqual(public["workload"]["source_batch_count"], 11)
        self.assertEqual(public["workload"]["calendar_day_count"], 8)
        self.assertEqual(public["workload"]["methodology_generation_count"], 10)
        self.assertEqual(public["workload"]["fixed_service_count"], 6)
        self.assertEqual(public["workload"]["complete_run_count"], 7)
        self.assertEqual(public["workload"]["latest_replicate_count"], 72)
        self.assertEqual(
            public["workload"]["latest_source_replicate_slot_count"],
            12,
        )
        self.assertEqual(
            public["workload"]["latest_incomplete_replicate_count"],
            0,
        )
        self.assertEqual(public["workload"]["latest_phase_count"], 720)
        self.assertFalse(public["workload"]["lifecycle_included"])
        self.assertEqual(
            public["workload"]["claim_scope"],
            "descriptive_observed_batch",
        )
        self.assertEqual(
            public["workload"]["historical_comparability"],
            "methodology_stratified",
        )
        self.assertIn(
            "CPU model",
            public["hourly_price"]["comparison_scope"],
        )
        self.assertEqual(len(public["workload"]["service_summary"]), 6)
        self.assertEqual(len(public["workload"]["phase_summary"]), 60)
        self.assertEqual(len(public["workload"]["run_history"]), 11)
        complete_runs = [
            row
            for row in public["workload"]["run_history"]
            if row["fixed_cohort_complete"]
        ]
        self.assertEqual(
            [row["benchmark_run_id"] for row in complete_runs],
            [
                "29937467891",
                "29982453127",
                "30019301067",
                "30322186937",
                "30510718771",
                "30589436441",
                "30655876610",
            ],
        )
        latest_run_rows = [
            row
            for row in public["workload"]["batch_history"]
            if row["benchmark_run_id"] == "30655876610"
        ]
        latest_run = public["workload"]["run_history"][-1]
        self.assertAlmostEqual(
            latest_run["median_estimated_cost_usd"],
            statistics.median(row["estimated_cost_usd"] for row in latest_run_rows),
        )
        self.assertAlmostEqual(
            latest_run["median_runtime_seconds"],
            statistics.median(row["runtime_seconds"] for row in latest_run_rows),
        )
        self.assertEqual(
            workload_card["headline"]["benchmark_run_id"],
            latest_run["benchmark_run_id"],
        )
        self.assertEqual(
            workload_card["headline"]["median_estimated_cost_usd"],
            latest_run["median_estimated_cost_usd"],
        )
        self.assertEqual(
            workload_card["headline"]["median_runtime_seconds"],
            latest_run["median_runtime_seconds"],
        )
        self.assertEqual(public["combined"]["rows"][0]["gpu_base_100"], 100.0)
        self.assertEqual(public["combined"]["rows"][1]["gpu_base_100"], 90.0)
        self.assertFalse(
            public["combined"]["coverage_history"][0]["comparison_eligible"]
        )
        self.assertEqual(
            public["combined"]["coverage_history"][0]["exclusion_reason"],
            "provider_coverage_below_10",
        )
        self.assertEqual(
            public["hourly_price"]["fixed_cohort_rate"][-1]["median_usd_per_hour"],
            0.4806,
        )
        self.assertEqual(
            public["hourly_price"]["fixed_cohort_rate"][-1]["p25_usd_per_hour"],
            0.3312,
        )
        self.assertEqual(
            public["hourly_price"]["fixed_cohort_rate"][-1]["p75_usd_per_hour"],
            0.6456,
        )
        modal = next(
            row
            for row in public["hourly_price"]["current_cross_section"]
            if row["series_id"] == "modal"
        )
        self.assertEqual(modal["processor_quantity"], 4.0)
        self.assertEqual(modal["price_usd_per_hour"], 0.759744)
        self.assertEqual(
            modal["processor_meter"],
            "max_requested_or_actual",
        )
        self.assertEqual(
            modal["billing_basis_label"],
            "higher of requested or actual use",
        )
        fly = next(
            row
            for row in public["hourly_price"]["current_cross_section"]
            if row["series_id"] == "fly-sprites"
        )
        self.assertEqual(fly["processor_meter"], "actual_usage")
        self.assertEqual(fly["memory_meter"], "actual_usage")
        self.assertEqual(
            {
                (
                    row["series_id"],
                    row["result_count"],
                    row["source_replicate_slot_count"],
                    row["incomplete_replicate_count"],
                )
                for row in public["workload"]["service_summary"]
            },
            {
                ("blaxel", 12, 12, 0),
                ("daytona-vm", 12, 12, 0),
                ("e2b", 12, 12, 0),
                ("modal-gvisor", 12, 12, 0),
                ("modal-vm", 12, 12, 0),
                ("novita", 12, 12, 0),
            },
        )
        self.assertEqual(
            {
                row["series_id"]
                for row in public["workload"]["service_summary"]
                if row["on_lower_left_frontier"]
            },
            {"daytona-vm", "novita"},
        )
        self.assertTrue(
            all(
                row["benchmark_source_url"]
                for row in public["workload"]["batch_history"]
            )
        )
        self.assertTrue(
            all(
                row["source_url"].startswith("https://")
                for row in public["hourly_price"]["rows"]
            )
        )
        self.assertTrue(
            all(
                row["source_url"].startswith("https://")
                for row in public["hourly_price"]["price_events"]
            )
        )
        self.assertTrue(
            all(
                row["source_url"].startswith("https://")
                for row in public["hourly_price"]["current_cross_section"]
            )
        )
        self.assertTrue(
            all(
                row["benchmark_source_url"].startswith("https://")
                for row in public["workload"]["latest_replicates"]
            )
        )
        public_text = json.dumps(public)
        self.assertNotIn("s3://", public_text)
        self.assertNotIn("source_run_ids", public["manifest"]["gpu_source_manifest"])
        self.assertEqual(
            [row["stage_id"] for row in public["utilization"]["rows"]],
            ["available", "rented", "allocated", "active", "productive"],
        )
        rented = public["utilization"]["rows"][1]
        self.assertEqual(rented["recommended_field_name"], "rented_capacity_ratio")
        self.assertIn(
            "does not show whether kernels", rented["what_it_does_not_support"]
        )

    def test_build_id_tracks_public_gpu_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            gpu_history = root / "benchmark-history.json"
            payload = {
                "manifest": {
                    "dashboard_exported_at": "2026-07-24T12:00:00Z",
                    "observed_at": "2026-07-24T12:00:00Z",
                    "run_id": "gold-test-a",
                },
                "rows": [_gpu_row("2026-07-24T12:00:00Z", 2.25, 10)],
            }
            gpu_history.write_text(json.dumps(payload), encoding="utf-8")
            first = build_sandbox_cost(
                output_root=str(root / "lake-a"),
                gpu_history_ref=str(gpu_history),
            )

            payload["manifest"]["run_id"] = "gold-test-b"
            gpu_history.write_text(json.dumps(payload), encoding="utf-8")
            second = build_sandbox_cost(
                output_root=str(root / "lake-b"),
                gpu_history_ref=str(gpu_history),
            )

        self.assertNotEqual(first.build_id, second.build_id)

    def test_build_accepts_parquet_gpu_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            gpu_history = root / "benchmark-history.parquet"
            write_parquet_rows(
                str(gpu_history),
                [
                    _gpu_row("2026-07-23T23:00:00Z", 2.5, 12),
                    _gpu_row("2026-07-24T12:00:00Z", 2.25, 14),
                ],
            )

            result = build_sandbox_cost(
                output_root=str(root / "lake"),
                gpu_history_ref=str(gpu_history),
            )
            manifest = json.loads(
                (root / "lake" / "gold" / "manifest.json").read_text()
            )

        self.assertEqual(result.row_counts["gpu_h100_daily_coverage"], 2)
        self.assertEqual(
            manifest["gpu_source_manifest"]["manifest_version"],
            "gpu_benchmark_history_parquet_v1",
        )
        self.assertEqual(
            manifest["gpu_source_manifest"]["row_counts"]["benchmark_history"],
            2,
        )

    def test_allowlisted_query_runs_through_datafusion(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            build_sandbox_cost(output_root=tmpdir)
            result = query_sandbox_gold(
                output_root=tmpdir,
                query_id="fixed-rate",
                limit=2,
            )

        self.assertEqual(result["engine"], "datafusion")
        self.assertEqual(len(result["rows"]), 2)
        self.assertEqual(result["rows"][0]["member_count"], 8)

    def test_utilization_ladder_query_runs_through_datafusion(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            build_sandbox_cost(output_root=tmpdir)
            result = query_sandbox_gold(
                output_root=tmpdir,
                query_id="utilization-ladder",
            )

        self.assertEqual(result["engine"], "datafusion")
        self.assertEqual(len(result["rows"]), 5)
        self.assertEqual(result["rows"][1]["stage_id"], "rented")

    def test_workload_run_history_query_preserves_intraday_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            build_sandbox_cost(output_root=tmpdir)
            result = query_sandbox_gold(
                output_root=tmpdir,
                query_id="workload-run-history",
            )

        self.assertEqual(result["engine"], "datafusion")
        self.assertEqual(len(result["rows"]), 11)
        july_22 = [
            row for row in result["rows"] if row["observed_date"] == "2026-07-22"
        ]
        self.assertEqual(len(july_22), 2)
        self.assertFalse(july_22[0]["fixed_cohort_complete"])
        self.assertTrue(july_22[1]["fixed_cohort_complete"])

    def test_repeated_intraday_runs_are_not_collapsed(self) -> None:
        prices = _read_local_json(PRICE_EVIDENCE)["rows"]
        runs = [
            _benchmark_run("run-a", "2026-07-23T07:00:00Z", 1.0),
            _benchmark_run("run-b", "2026-07-23T17:00:00Z", 2.0),
        ]

        rows = extract_benchmark_rows(runs=runs, prices=prices)

        self.assertEqual(len(rows), 2)
        self.assertEqual(
            [row["benchmark_run_id"] for row in rows],
            ["run-a", "run-b"],
        )
        self.assertEqual([row["point_order"] for row in rows], [1, 2])

    def test_aligned_replicates_and_phases_are_retained(self) -> None:
        prices = _read_local_json(PRICE_EVIDENCE)["rows"]
        run = _benchmark_run(
            "run-replicated",
            "2026-07-23T17:00:00Z",
            1.5,
            replicate_values=[1.0, 2.0],
        )

        evidence = extract_benchmark_evidence(runs=[run], prices=prices)

        self.assertEqual(len(evidence["batch_rows"]), 1)
        self.assertEqual(len(evidence["replicate_rows"]), 2)
        self.assertEqual(len(evidence["phase_rows"]), 20)
        self.assertEqual(
            [row["runtime_seconds"] for row in evidence["replicate_rows"]],
            [10.0, 20.0],
        )
        self.assertEqual(evidence["batch_rows"][0]["runtime_seconds"], 15.0)
        self.assertTrue(evidence["batch_rows"][0]["replicate_data_available"])
        self.assertEqual(
            evidence["batch_rows"][0]["observation_level"],
            "provider_batch_summary",
        )

    def test_workload_version_drift_is_rejected(self) -> None:
        prices = _read_local_json(PRICE_EVIDENCE)["rows"]
        run = _benchmark_run("run-drift", "2026-07-23T17:00:00Z", 1.0)
        run["providers"][0]["metrics"][0]["appVersion"] = "0" * 40

        with self.assertRaisesRegex(ValueError, "Workload drift"):
            extract_benchmark_evidence(runs=[run], prices=prices)

    def test_misaligned_replicate_indices_are_rejected(self) -> None:
        prices = _read_local_json(PRICE_EVIDENCE)["rows"]
        run = _benchmark_run(
            "run-misaligned",
            "2026-07-23T17:00:00Z",
            1.5,
            replicate_values=[1.0, 2.0],
        )
        run["providers"][0]["metrics"][0]["replicates"][1]["index"] = 7

        with self.assertRaisesRegex(ValueError, "not aligned"):
            extract_benchmark_evidence(runs=[run], prices=prices)

    def test_historical_merge_rejects_changed_source_result(self) -> None:
        row = _read_local_json(BENCHMARK_EVIDENCE)["batch_rows"][0]
        changed = copy.deepcopy(row)
        changed["runtime_seconds"] += 1

        with self.assertRaisesRegex(ValueError, "changed an existing"):
            _merge_historical_rows([row], [changed])


def _gpu_row(observed_at: str, price: float, providers: int) -> dict[str, object]:
    return {
        "gold_observed_at": observed_at,
        "benchmark_family_id": "H100",
        "benchmark_usd_gpu_hr": price,
        "provider_count": providers,
        "included_offer_count": providers,
        "provider_floor_p25_usd_gpu_hr": price * 0.9,
        "provider_floor_p75_usd_gpu_hr": price * 1.1,
        "methodology_version": "advertised_provider_floor_median_v1",
        "benchmark_basis": "advertised_hourly",
        "calculated_at": observed_at,
    }


def _benchmark_run(
    run_id: str,
    generated_at: str,
    task_mean: float,
    *,
    replicate_values: list[float] | None = None,
) -> dict[str, object]:
    metrics = []
    for argument, metric_id in TASK_ARGUMENTS:
        values = replicate_values or [task_mean]
        metric: dict[str, object] = {
            "sourceFile": "realworld-better-auth/pts_realworld-better-auth.xml",
            "metricId": metric_id,
            "appVersion": WORKLOAD_APP_VERSION,
            "arguments": argument,
            "aggregates": {
                "mean": sum(values) / len(values),
                "n": len(values),
            },
            "samples": values,
        }
        if replicate_values is not None:
            metric["replicates"] = [
                {"index": index, "samples": [value]}
                for index, value in enumerate(values)
            ]
        metrics.append(metric)
    return {
        "runId": run_id,
        "generatedAt": generated_at,
        "sha": "a" * 40,
        "targetSpec": {"vcpus": 4, "memoryGb": 8, "diskGb": 40},
        "providers": [
            {
                "providerId": "e2b",
                "validationStatus": "validated",
                "specMatched": True,
                "observedSpecs": {
                    "vcpus": 4,
                    "memoryGb": 8,
                    "diskGb": 40,
                    "cpuModel": "test",
                },
                "gaps": [],
                "metrics": metrics,
            }
        ],
    }


if __name__ == "__main__":
    unittest.main()
