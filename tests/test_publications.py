import json
import struct
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from the_compute_bazaar.prices.publications import (
    IMAGE_HEIGHT,
    IMAGE_WIDTH,
    PUBLICATION_SCHEMA_VERSION,
    publish_gpu_benchmark_publications,
    render_gpu_benchmark_publication,
)
from the_compute_bazaar.publication_contract import (
    PUBLICATION_ROUTE_SCHEMA_VERSION,
    PublicationRoute,
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
                / "full-history"
                / f"{result['revision']}.html"
            )
            image = page.with_suffix(".png")

            self.assertEqual(result["publication_count"], 12)
            self.assertEqual(repeated["revision"], result["revision"])
            self.assertEqual(manifest["publication_count"], 12)
            self.assertEqual(
                h100_all["url"],
                "https://data.example.test/publications/gpu-index/"
                f"h100/full-history/{result['revision']}",
            )
            self.assertEqual(
                cards["H100"]["publication"]["schema_version"],
                PUBLICATION_SCHEMA_VERSION,
            )
            self.assertEqual(
                cards["H100"]["publication"]["route_schema_version"],
                PUBLICATION_ROUTE_SCHEMA_VERSION,
            )
            self.assertEqual(
                cards["H100"]["publication"]["default_range"],
                "1d",
            )
            self.assertEqual(h100_all["view"]["label"], "full retained history")
            self.assertEqual(h100_all["change_label"], "Up 22.5% since 20 Jul 2026")
            self.assertEqual(h100_all["change_direction"], "up")
            self.assertNotIn("/v2/", h100_all["url"])
            self.assertNotIn("gold-market", h100_all["url"])
            self.assertFalse(h100_all["url"].endswith(".html"))
            self.assertRegex(
                result["revision"],
                r"^2026-07-29-0000-utc-[a-f0-9]{10}$",
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
            self.assertIn(
                f'<meta name="twitter:url" content="{h100_all["url"]}">',
                html,
            )
            self.assertIn(
                "H100 GPU Price Index | $2.45/GPU-hour "
                "| Up 22.5% since 20 Jul 2026",
                html,
            )
            self.assertIn(
                "H100 / full retained history / up 22.5% since 20 jul 2026",
                html,
            )
            self.assertIn("Open live chart", html)
            self.assertNotIn("s3://", html)

            png = image.read_bytes()
            self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
            width, height = struct.unpack(">II", png[16:24])
            self.assertEqual((width, height), (IMAGE_WIDTH, IMAGE_HEIGHT))
            self.assertEqual(png[25], 2)

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

    def test_public_host_change_creates_a_new_immutable_revision(self) -> None:
        cards = _cards()

        with TemporaryDirectory() as temporary_directory:
            first = publish_gpu_benchmark_publications(
                output_root=temporary_directory,
                cards=cards,
                public_base_url="https://old.example.test",
                article_url="https://example.test/compute.html",
            )
            second = publish_gpu_benchmark_publications(
                output_root=temporary_directory,
                cards=cards,
                public_base_url="https://new.example.test",
                article_url="https://example.test/compute.html",
            )

            self.assertNotEqual(first["revision"], second["revision"])
            for result in (first, second):
                page = (
                    Path(temporary_directory)
                    / "publications"
                    / "gpu-index"
                    / "h100"
                    / "full-history"
                    / f"{result['revision']}.html"
                )
                self.assertTrue(page.is_file())

    def test_one_day_publication_exposes_human_change_metadata(self) -> None:
        cards = _cards()

        with TemporaryDirectory() as temporary_directory:
            publish_gpu_benchmark_publications(
                output_root=temporary_directory,
                cards=cards,
                public_base_url="https://data.example.test",
                article_url="https://example.test/compute.html",
            )

            publication = cards["B200"]["publication"]["ranges"]["1d"]

            self.assertIn("/gpu-index/b200/1-day/", publication["url"])
            self.assertEqual(publication["subject"]["label"], "B200 GPU")
            self.assertEqual(publication["view"]["label"], "1 day")
            self.assertEqual(publication["change_pct"], 1.136364)
            self.assertEqual(publication["change_label"], "Up 1.1% over 1 day")
            self.assertEqual(publication["change_direction"], "up")
            self.assertIn("B200 GPU Price Index", publication["title"])
            self.assertIn("Up 1.1% over 1 day", publication["title"])

    def test_shared_route_contract_is_card_agnostic(self) -> None:
        route = PublicationRoute.create(
            card_id="Compute Deal",
            subject_id="H100 / EU West",
            view_id="Signed Terms",
            observed_at=datetime(2026, 7, 30, 4, tzinfo=timezone.utc),
            content_digest="ABCDEF1234567890",
        )

        self.assertEqual(
            route.public_path,
            "publications/compute-deal/h100-eu-west/signed-terms/"
            "2026-07-30-0400-utc-abcdef1234",
        )
        self.assertEqual(
            route.page_path,
            "publications/compute-deal/h100-eu-west/signed-terms/"
            "2026-07-30-0400-utc-abcdef1234.html",
        )
        self.assertEqual(
            route.as_dict()["page_object_path"],
            route.page_path,
        )
        self.assertEqual(
            route.publication_id,
            "compute-deal:h100-eu-west:signed-terms:"
            "2026-07-30-0400-utc-abcdef1234",
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
