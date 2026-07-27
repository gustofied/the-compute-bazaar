import json
import unittest

from the_compute_bazaar.prices.market_run import _public_market_run_manifest
from the_compute_bazaar.prices.public_views import market_overview_view


class PublicViewTests(unittest.TestCase):
    def test_market_run_summary_removes_private_s3_references(self) -> None:
        public = _public_market_run_manifest(
            {
                "market_run_id": "market-test",
                "status": "success",
                "data_quality": {
                    "sandbox_cost": {
                        "build_id": "sandbox-test",
                        "manifest_ref": "s3://private/lake/manifest.json",
                    },
                    "providers": ["vast"],
                },
            }
        )

        self.assertEqual(
            public["data_quality"]["sandbox_cost"],
            {"build_id": "sandbox-test"},
        )
        self.assertNotIn("s3://", json.dumps(public))

    def test_market_overview_keeps_only_compact_run_fields(self) -> None:
        overview = market_overview_view(
            manifest={
                "market_run_id": "market-test",
                "status": "success",
                "observed_at": "2026-07-27T20:00:00Z",
                "successful_providers": ["vast"],
                "failed_providers": [],
                "data_quality": {
                    "manifest_ref": "s3://private/lake/manifest.json"
                },
            },
            benchmark_cards=[],
        )

        self.assertEqual(
            overview["data"]["market_run"]["market_run_id"],
            "market-test",
        )
        self.assertNotIn("data_quality", overview["data"]["market_run"])
        self.assertNotIn("s3://", json.dumps(overview))


if __name__ == "__main__":
    unittest.main()
