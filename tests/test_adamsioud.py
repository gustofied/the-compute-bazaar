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

        self.assertIn("data-sandbox-cost", article)
        self.assertIn(
            "Four vCPUs and 8 GiB, before and after the sandbox layer",
            article,
        )
        self.assertIn(
            "Measured phase time; marginal rate-card cost estimated",
            article,
        )
        self.assertIn('id="sandbox-job-scatter"', article)
        self.assertIn('id="sandbox-phase-summary"', article)
        self.assertIn('id="sandbox-batch-history"', article)
        self.assertIn('id="sandbox-batch-table-body"', article)
        self.assertIn('id="sandbox-combined-chart"', article)
        self.assertIn('id="sandbox-coverage-chart"', article)
        self.assertIn('id="vm-hourly-chart"', article)
        self.assertIn('src="./sandbox-cost.js?v=12"', article)
        self.assertIn("sandbox-cost.json", script)
        self.assertIn('"sandbox_cost_gold_v4"', script)
        self.assertIn("effectiveCssZoom", script)
        self.assertIn("createVmHourlyChart", script)
        self.assertIn("createRateHistoryChart", script)
        self.assertIn("partial source check", script)
        self.assertIn("latest complete", script)
        self.assertIn('id="vm-current-rates"', article)
        self.assertIn('id="vm-marketplace-rates"', article)
        self.assertIn('id="vm-capacity-table-body"', article)
        self.assertIn("createJobDistributionChart", script)
        self.assertIn("createBatchHistoryChart", script)
        self.assertEqual(
            payload["manifest"]["manifest_version"],
            "sandbox_cost_gold_v4",
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
        self.assertEqual(len(payload["workload"]["phase_summary"]), 60)
        self.assertEqual(len(payload["workload"]["batch_history"]), 38)
        self.assertEqual(len(payload["workload"]["latest_replicates"]), 69)
        self.assertFalse(payload["workload"]["lifecycle_included"])


if __name__ == "__main__":
    unittest.main()
