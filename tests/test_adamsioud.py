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
        self.assertIn("Sandbox rates, normalized to one machine", article)
        self.assertIn(
            "Runtime measured, processor-and-memory cost estimated",
            article,
        )
        self.assertIn('id="sandbox-job-scatter"', article)
        self.assertIn('id="sandbox-combined-chart"', article)
        self.assertIn('id="sandbox-coverage-chart"', article)
        self.assertIn('src="./sandbox-cost.js?v=5"', article)
        self.assertIn("sandbox-cost.json", script)
        self.assertIn('manifestVersion !== "sandbox_cost_gold_v2"', script)
        self.assertIn("effectiveCssZoom", script)
        self.assertIn("createJobScatter", script)
        self.assertEqual(
            payload["manifest"]["manifest_version"],
            "sandbox_cost_gold_v2",
        )
        self.assertEqual(
            payload["manifest"]["row_counts"]["sandbox_hourly_price_series"],
            33,
        )
        self.assertEqual(
            payload["manifest"]["row_counts"]["sandbox_price_events"],
            10,
        )
        self.assertEqual(
            payload["manifest"]["row_counts"]["gpu_h100_daily_coverage"],
            37,
        )
        self.assertEqual(
            payload["manifest"]["row_counts"]["gpu_h100_eligible_history"],
            30,
        )
        self.assertEqual(
            payload["manifest"]["row_counts"]["sandbox_gpu_cpu_common_start"],
            30,
        )
        self.assertEqual(payload["same_job_cost"]["comparable_run_count"], 7)
        self.assertEqual(payload["same_job_cost"]["calendar_day_count"], 5)
        self.assertEqual(len(payload["same_job_cost"]["service_summary"]), 6)
        self.assertEqual(len(payload["same_job_cost"]["rows"]), 38)


if __name__ == "__main__":
    unittest.main()
