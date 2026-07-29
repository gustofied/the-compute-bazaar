import json
import struct
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from the_compute_bazaar.prices.publications import (
    IMAGE_HEIGHT,
    IMAGE_WIDTH,
    publish_gpu_benchmark_publications,
    render_gpu_benchmark_publication,
)


class GpuPublicationTests(unittest.TestCase):
    def test_publish_creates_immutable_pages_and_social_images(self) -> None:
        cards = _cards()

        with TemporaryDirectory() as temporary_directory:
            result = publish_gpu_benchmark_publications(
                output_root=temporary_directory,
                cards=cards,
                public_base_url="https://data.example.test",
                article_url="https://example.test/compute.html",
            )
            root = Path(temporary_directory)
            repeated = publish_gpu_benchmark_publications(
                output_root=temporary_directory,
                cards=cards,
                public_base_url="https://data.example.test",
                article_url="https://example.test/compute.html",
            )
            manifest = json.loads(
                Path(result["manifest_ref"]).read_text(encoding="utf-8")
            )
            h100_all = cards["H100"]["publication"]["ranges"]["all"]
            page = (
                root
                / "publications"
                / "gpu-index"
                / "h100"
                / "all"
                / f"{result['revision']}.html"
            )
            image = page.with_suffix(".png")

            self.assertEqual(result["publication_count"], 12)
            self.assertEqual(repeated["revision"], result["revision"])
            self.assertEqual(manifest["publication_count"], 12)
            self.assertEqual(
                h100_all["url"],
                f"https://data.example.test/publications/gpu-index/h100/all/"
                f"{result['revision']}.html",
            )
            self.assertIn(
                "?card=gpu-index&view=detail&gpu=H100&range=all",
                h100_all["live_url"],
            )
            self.assertTrue(page.is_file())
            self.assertTrue(image.is_file())

            html = page.read_text(encoding="utf-8")
            self.assertIn('<meta property="og:type" content="article">', html)
            self.assertIn('<meta property="og:image"', html)
            self.assertIn(
                '<meta name="twitter:card" content="summary_large_image">',
                html,
            )
            self.assertIn("Open live chart", html)
            self.assertNotIn("s3://", html)

            png = image.read_bytes()
            self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
            width, height = struct.unpack(">II", png[16:24])
            self.assertEqual((width, height), (IMAGE_WIDTH, IMAGE_HEIGHT))

    def test_render_rejects_unknown_family_and_range(self) -> None:
        cards = _cards()

        with self.assertRaisesRegex(ValueError, "Unknown GPU publication family"):
            render_gpu_benchmark_publication(
                cards=cards,
                selected_family="A100",
                range_id="all",
            )
        with self.assertRaisesRegex(ValueError, "Unknown GPU publication range"):
            render_gpu_benchmark_publication(
                cards=cards,
                selected_family="H100",
                range_id="30d",
            )


def _cards() -> dict[str, dict[str, object]]:
    start = datetime(2026, 7, 20, tzinfo=timezone.utc)
    cards: dict[str, dict[str, object]] = {}
    for family_index, family in enumerate(("H100", "H200", "B200", "B300")):
        rows = []
        for observation_index in range(10):
            observed_at = start + timedelta(days=observation_index)
            value = 2.0 + family_index + observation_index * 0.05
            rows.append(
                {
                    "observed_at": observed_at.isoformat(),
                    "value": value,
                    "lower": value * 0.9,
                    "upper": value * 1.1,
                    "provider_count": 7,
                    "offer_count": 20,
                    "run_id": f"gold-market-test-{observation_index:02d}",
                }
            )
        cards[family] = {
            "schema_version": "compute_bazaar_card_v1",
            "card_type": "gpu_benchmark",
            "card_id": f"gpu-benchmark:{family.lower()}",
            "as_of": rows[-1]["observed_at"],
            "series": rows,
            "coverage": {
                "provider_count": 7,
                "offer_count": 20,
            },
        }
    return cards


if __name__ == "__main__":
    unittest.main()
