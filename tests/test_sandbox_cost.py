import copy
import json
import tempfile
import unittest
from pathlib import Path

from the_compute_bazaar.sandbox_cost.pipeline import (
    BENCHMARK_EVIDENCE,
    PRICE_EVIDENCE,
    SOURCE_MANIFEST,
    _read_local_json,
    build_sandbox_cost,
    query_sandbox_gold,
    validate_evidence,
)
from the_compute_bazaar.sandbox_cost.refresh import (
    _merge_historical_rows,
    _parse_index,
    extract_benchmark_rows,
)


class SandboxCostEvidenceTests(unittest.TestCase):
    def test_canonical_evidence_counts_and_shape(self) -> None:
        summary = validate_evidence()

        self.assertEqual(summary["price_observation_count"], 33)
        self.assertEqual(summary["price_service_count"], 11)
        self.assertEqual(summary["benchmark_result_count"], 38)
        self.assertEqual(summary["benchmark_service_count"], 6)
        self.assertEqual(summary["benchmark_run_count"], 7)
        self.assertEqual(summary["benchmark_calendar_day_count"], 5)
        self.assertEqual(len(summary["fixed_members"]), 8)

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
        benchmarks["rows"][0]["vcpus"] = 2

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


class SandboxCostPipelineTests(unittest.TestCase):
    def test_build_is_deterministic_and_public_payload_retains_all_runs(self) -> None:
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
                            _gpu_row("2026-07-23T23:00:00Z", 2.5, 8),
                            _gpu_row("2026-07-24T12:00:00Z", 2.25, 10),
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
            public = json.loads(
                (root / "dashboard" / "sandbox-cost.json").read_text()
            )

        self.assertEqual(first.build_id, second.build_id)
        self.assertEqual(first.row_counts["sandbox_hourly_price_series"], 33)
        self.assertEqual(first.row_counts["sandbox_same_job_cost"], 38)
        self.assertEqual(first.row_counts["sandbox_combined_base100"], 2)
        self.assertEqual(public["same_job_cost"]["comparable_run_count"], 7)
        self.assertEqual(public["same_job_cost"]["calendar_day_count"], 5)
        self.assertEqual(public["combined"]["rows"][0]["gpu_base_100"], 100.0)
        self.assertEqual(public["combined"]["rows"][1]["gpu_base_100"], 90.0)
        self.assertEqual(
            public["hourly_price"]["fixed_membership_average"][-1][
                "average_usd_per_hour"
            ],
            0.456,
        )
        self.assertTrue(
            all(row["benchmark_source_url"] for row in public["same_job_cost"]["rows"])
        )
        public_text = json.dumps(public)
        self.assertNotIn("s3://", public_text)
        self.assertNotIn("source_run_ids", public["manifest"]["gpu_source_manifest"])

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

    def test_allowlisted_query_runs_through_datafusion(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            build_sandbox_cost(output_root=tmpdir)
            result = query_sandbox_gold(
                output_root=tmpdir,
                query_id="fixed-average",
                limit=2,
            )

        self.assertEqual(result["engine"], "datafusion")
        self.assertEqual(len(result["rows"]), 2)
        self.assertEqual(result["rows"][0]["member_count"], 8)

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

    def test_historical_merge_rejects_changed_source_result(self) -> None:
        row = _read_local_json(BENCHMARK_EVIDENCE)["rows"][0]
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
        "methodology_version": "advertised_provider_floor_median_v1",
        "benchmark_basis": "advertised_hourly",
        "calculated_at": observed_at,
    }


def _benchmark_run(
    run_id: str,
    generated_at: str,
    task_mean: float,
) -> dict[str, object]:
    metrics = [
        {
            "sourceFile": "realworld-better-auth/pts_realworld-better-auth.xml",
            "metricId": f"realworld_better_auth_task_{index}",
            "aggregates": {"mean": task_mean},
        }
        for index in range(10)
    ]
    return {
        "runId": run_id,
        "generatedAt": generated_at,
        "targetSpec": {"vcpus": 4, "memoryGb": 8, "diskGb": 40},
        "providers": [
            {
                "providerId": "e2b",
                "validationStatus": "validated",
                "specMatched": True,
                "metrics": metrics,
            }
        ],
    }


if __name__ == "__main__":
    unittest.main()
