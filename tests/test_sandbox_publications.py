from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from the_compute_bazaar.prices.sandbox_publications import (
    publish_sandbox_workload_publication,
)


class SandboxPublicationsTest(unittest.TestCase):
    def test_publishes_today_seven_day_and_full_history_cards(self) -> None:
        card = {
            "as_of": "2026-08-06T03:32:00Z",
            "headline": {"median_estimated_cost_usd": 0.022},
            "data": {
                "workload": {
                    "service_summary": [
                        {
                            "series_id": "alpha",
                            "series_label": "Alpha",
                            "series_order": 1,
                            "median_estimated_cost_usd": 0.018,
                            "p25_estimated_cost_usd": 0.016,
                            "p75_estimated_cost_usd": 0.020,
                        },
                        {
                            "series_id": "beta",
                            "series_label": "Beta",
                            "series_order": 2,
                            "median_estimated_cost_usd": 0.026,
                            "p25_estimated_cost_usd": 0.024,
                            "p75_estimated_cost_usd": 0.029,
                        },
                    ],
                    "measured_history": [
                        {
                            "series_id": "alpha",
                            "series_label": "Alpha",
                            "series_order": 1,
                            "generated_at": "2026-07-20T12:00:00Z",
                            "median_estimated_cost_usd": 0.021,
                        },
                        {
                            "series_id": "beta",
                            "series_label": "Beta",
                            "series_order": 2,
                            "generated_at": "2026-07-20T12:00:00Z",
                            "median_estimated_cost_usd": 0.031,
                        },
                        {
                            "series_id": "alpha",
                            "series_label": "Alpha",
                            "series_order": 1,
                            "generated_at": "2026-08-06T03:32:00Z",
                            "median_estimated_cost_usd": 0.018,
                        },
                        {
                            "series_id": "beta",
                            "series_label": "Beta",
                            "series_order": 2,
                            "generated_at": "2026-08-06T03:32:00Z",
                            "median_estimated_cost_usd": 0.026,
                        },
                    ],
                }
            },
        }

        with tempfile.TemporaryDirectory() as directory:
            result = publish_sandbox_workload_publication(
                output_root=directory,
                workload_card=card,
                public_base_url="https://bazaar.example",
                article_url="https://article.example/compute.html",
            )

            self.assertEqual(result["publication_count"], 3)
            publication = card["publication"]
            self.assertEqual(publication["default_range"], "7d")
            self.assertEqual(set(publication["ranges"]), {"latest", "7d", "all"})
            self.assertEqual(
                publication["states"]["cost"]["url"],
                publication["ranges"]["latest"]["url"],
            )

            for range_id, link in publication["ranges"].items():
                self.assertIn(f"sandboxRange={range_id}", link["live_url"])
                image_path = Path(directory) / link["image_url"].removeprefix(
                    "https://bazaar.example/"
                )
                page_path = (
                    Path(directory)
                    / link["url"].removeprefix("https://bazaar.example/")
                ).with_suffix(".html")
                self.assertTrue(image_path.exists())
                self.assertTrue(page_path.exists())
                with Image.open(io.BytesIO(image_path.read_bytes())) as image:
                    self.assertEqual(image.size, (1200, 630))


if __name__ == "__main__":
    unittest.main()
