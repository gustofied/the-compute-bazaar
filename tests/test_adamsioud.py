import json
import unittest
from pathlib import Path

from the_compute_bazaar.adamsioud import create_app


class AdamSioudServerTests(unittest.TestCase):
    def test_publication_server_registers_site_and_snapshot_routes(self) -> None:
        app = create_app(site_dir=Path("external/AdamSioud"), snapshot_source="local")
        paths = {getattr(route, "path", "") for route in app.routes}

        self.assertIn("/api/health", paths)
        self.assertIn("/api/dashboard-snapshots/{filename}", paths)
        self.assertIn("/api/snapshots/{name}", paths)
        self.assertIn("/", paths)

    def test_compute_article_contains_the_maintained_sandbox_views(self) -> None:
        article_root = Path("external/AdamSioud/exemplars/compute")
        article = (article_root / "feeling_the_compute.html").read_text(
            encoding="utf-8"
        )
        script = (article_root / "sandbox-cost.js").read_text(encoding="utf-8")
        payload = json.loads(
            (article_root / "sandbox-cost.json").read_text(encoding="utf-8")
        )
        market_state = json.loads(
            (article_root / "market-state.json").read_text(encoding="utf-8")
        )

        self.assertIn("data-sandbox-cost", article)
        self.assertIn(
            "Four vCPUs and 8 GiB, before and after the sandbox layer",
            article,
        )
        self.assertIn(
            "What the same software job costs on each sandbox",
            article,
        )
        self.assertIn("Estimated cost of the same job", article)
        self.assertIn("Cost ranking", article)
        self.assertNotIn('data-job-metric="time"', article)
        self.assertNotIn('data-job-metric="cost"', article)
        self.assertIn("Inspect the seven underlying VM offers", article)
        self.assertIn("Public VM/VPS and managed sandbox prices", article)
        self.assertIn("all seven VM offers", article)
        self.assertIn('data-relative-series="gpu"', article)
        self.assertIn('data-relative-series="vm"', article)
        self.assertIn('data-relative-series="sandbox"', article)
        self.assertIn('data-occupancy-provider="akash"', article)
        self.assertIn('data-occupancy-provider="clore"', article)
        self.assertIn('id="sandbox-job-scatter"', article)
        self.assertIn('id="sandbox-phase-summary"', article)
        self.assertIn('id="sandbox-batch-table-body"', article)
        self.assertIn('id="sandbox-combined-chart"', article)
        self.assertIn('id="sandbox-coverage-chart"', article)
        self.assertIn('id="market-state-current"', article)
        self.assertIn('id="market-occupancy-chart"', article)
        self.assertIn('id="market-state-availability"', article)
        self.assertNotIn('id="vm-hourly-chart"', article)
        self.assertNotIn('id="sandbox-batch-history"', article)
        self.assertIn('src="./sandbox-cost.js?v=20"', article)
        self.assertIn("sandbox-cost.json", script)
        self.assertIn('"sandbox_cost_gold_v5"', script)
        self.assertNotIn('"sandbox_cost_gold_v4"', script)
        self.assertNotIn("summarizeJobs", script)
        self.assertIn("renderJobRanking", script)
        self.assertNotIn("activeMetric", script)
        self.assertNotIn("sandbox-job-view-note", script)
        self.assertIn("workload.service_summary", script)
        self.assertIn("effectiveCssZoom", script)
        self.assertIn("createRateHistoryChart", script)
        self.assertIn("partial source check", script)
        self.assertIn("latest complete", script)
        self.assertIn('id="vm-current-rates"', article)
        self.assertIn('id="vm-marketplace-rates"', article)
        self.assertIn('id="vm-capacity-table-body"', article)
        self.assertIn("createJobDistributionChart", script)
        self.assertIn("renderMarketStateSummary", script)
        self.assertIn("createMarketOccupancyChart", script)
        self.assertIn("sandbox-capacity-total", script)
        self.assertIn("base_100", script)
        self.assertIn("market-state.json", script)
        self.assertEqual(
            market_state["schema_version"],
            "compute_market_state_public_v1",
        )
        self.assertEqual(
            market_state["current_row_count"],
            len(market_state["current_rows"]),
        )
        self.assertEqual(
            market_state["history_row_count"],
            len(market_state["history_rows"]),
        )
        self.assertEqual(
            {
                row["measurement_kind"]
                for row in market_state["current_rows"]
            },
            {"rental_occupancy", "availability_pressure"},
        )
        self.assertTrue(
            all(
                row["measurement_kind"] == "rental_occupancy"
                and row["resource_type"] == "ALL_GPU"
                for row in market_state["history_rows"]
            )
        )
        self.assertNotIn("raw_ref", json.dumps(market_state))
        self.assertNotIn("s3://", json.dumps(market_state))
        self.assertEqual(
            payload["manifest"]["manifest_version"],
            "sandbox_cost_gold_v5",
        )
        self.assertEqual(
            payload["manifest"]["row_counts"]["vm_capacity_current"],
            4,
        )
        self.assertEqual(
            payload["manifest"]["row_counts"]["vm_capacity_expanded_rate"],
            len(payload["vm_capacity"]["fixed_cohort_rate"]),
        )
        self.assertEqual(
            payload["manifest"]["row_counts"]["vm_capacity_fixed_rate"],
            len(payload["vm_capacity"]["legacy_fixed_cohort_rate"]),
        )
        self.assertGreaterEqual(
            payload["manifest"]["row_counts"]["vm_capacity_observed_rate"],
            2,
        )
        self.assertTrue(
            all(
                {
                    "base_observed_at",
                    "base_median_usd_per_hour",
                    "base_100",
                    "p25_base_100",
                    "p75_base_100",
                    "minimum_base_100",
                    "maximum_base_100",
                }.issubset(row)
                for row in payload["vm_capacity"]["observed_market_rate"]
            )
        )
        self.assertEqual(
            payload["manifest"]["row_counts"]["vm_capacity_expanded_current"],
            7,
        )
        self.assertEqual(
            len(payload["vm_capacity"]["current_cross_section"]),
            7,
        )
        self.assertEqual(len(payload["vm_capacity"]["marketplace_indications"]), 1)
        self.assertNotIn(
            "raw_refs_json",
            json.dumps(payload["vm_capacity"]),
        )
        self.assertEqual(
            payload["manifest"]["row_counts"]["sandbox_hourly_price_series"],
            33,
        )
        self.assertEqual(
            payload["manifest"]["row_counts"]["sandbox_price_events"],
            10,
        )
        coverage_count = payload["manifest"]["row_counts"]["gpu_h100_daily_coverage"]
        eligible_count = payload["manifest"]["row_counts"]["gpu_h100_eligible_history"]
        self.assertGreaterEqual(coverage_count, 37)
        self.assertEqual(
            coverage_count,
            len(payload["combined"]["coverage_history"]),
        )
        self.assertGreaterEqual(eligible_count, 30)
        self.assertEqual(
            payload["manifest"]["row_counts"]["sandbox_gpu_cpu_common_start"],
            eligible_count,
        )
        self.assertEqual(len(payload["combined"]["rows"]), eligible_count)
        self.assertEqual(payload["workload"]["source_batch_count"], 7)
        self.assertEqual(payload["workload"]["calendar_day_count"], 5)
        self.assertEqual(payload["workload"]["methodology_generation_count"], 6)
        self.assertEqual(payload["workload"]["latest_replicate_count"], 69)
        self.assertEqual(
            payload["workload"]["latest_source_replicate_slot_count"],
            12,
        )
        self.assertEqual(
            payload["workload"]["latest_incomplete_replicate_count"],
            3,
        )
        self.assertEqual(payload["workload"]["latest_phase_count"], 690)
        self.assertEqual(len(payload["workload"]["service_summary"]), 6)
        self.assertTrue(
            all(
                {
                    "median_runtime_seconds",
                    "p25_runtime_seconds",
                    "p75_runtime_seconds",
                    "median_estimated_cost_usd",
                    "p25_estimated_cost_usd",
                    "p75_estimated_cost_usd",
                }.issubset(row)
                for row in payload["workload"]["service_summary"]
            )
        )
        self.assertEqual(len(payload["workload"]["phase_summary"]), 60)
        self.assertEqual(len(payload["workload"]["batch_history"]), 38)
        self.assertEqual(len(payload["workload"]["latest_replicates"]), 69)
        self.assertFalse(payload["workload"]["lifecycle_included"])
        self.assertEqual(
            payload["manifest"]["row_counts"][
                "compute_utilization_public_ladder"
            ],
            5,
        )
        self.assertEqual(
            [row["stage_id"] for row in payload["utilization"]["rows"]],
            ["available", "rented", "allocated", "active", "productive"],
        )


if __name__ == "__main__":
    unittest.main()
