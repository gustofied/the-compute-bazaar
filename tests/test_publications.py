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
    publish_sandbox_market_publications,
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
                "?card=gpu-index&view=share&present=card&gpu=H100&range=all",
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
                "H100 GPU Price Index | $2.45/GPU-hour | Up 22.5% since 20 Jul 2026",
                html,
            )
            self.assertIn(
                "H100 / full retained history / up 22.5% since 20 jul 2026",
                html,
            )
            self.assertIn("Open interactive card", html)
            self.assertIn("window.location.replace(", html)
            self.assertIn(
                "card=gpu-index&view=share&present=card&gpu=H100&range=all",
                html,
            )
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
            "compute-deal:h100-eu-west:signed-terms:2026-07-30-0400-utc-abcdef1234",
        )


class SandboxPublicationTests(unittest.TestCase):
    def test_publish_creates_preview_wrappers_for_every_live_card_state(
        self,
    ) -> None:
        rates, workload, relative = _sandbox_cards()

        with TemporaryDirectory() as temporary_directory:
            result = publish_sandbox_market_publications(
                output_root=temporary_directory,
                rates_card=rates,
                workload_card=workload,
                relative_card=relative,
                public_base_url="https://data.example.test",
                article_url="https://example.test/compute.html",
            )
            repeated = publish_sandbox_market_publications(
                output_root=temporary_directory,
                rates_card=rates,
                workload_card=workload,
                relative_card=relative,
                public_base_url="https://data.example.test",
                article_url="https://example.test/compute.html",
            )
            rate_publication = rates["publication"]["states"]["rates"]
            workload_publication = workload["publication"]["states"]["cost"]
            relative_publication = relative["publication"]["states"]["gpu:7d"]

            self.assertEqual(result["publication_count"], 12)
            self.assertEqual(repeated["revision"], result["revision"])
            self.assertEqual(
                rates["publication"]["kind"],
                "crawler_preview_live_handoff",
            )
            self.assertIn(
                "/publications/sandbox-cost/rates/hourly-rate/",
                rate_publication["url"],
            )
            self.assertIn(
                "?card=sandbox-cost&view=share&present=card&sandbox=rates",
                rate_publication["live_url"],
            )
            self.assertIn(
                "Sandbox / public hourly rate", rate_publication["display_line"]
            )
            self.assertIn(
                "?card=sandbox-cost&view=share&present=card"
                "&sandbox=workload&measure=cost",
                workload_publication["live_url"],
            )
            self.assertIn(
                "?card=relative-prices&view=share&present=card"
                "&relativeRange=7d&relativeBand=gpu",
                relative_publication["live_url"],
            )
            self.assertEqual(
                relative_publication["change_label"],
                "Up 6.9% over 7 days",
            )
            self.assertFalse(rate_publication["url"].endswith(".html"))

            relative_page = (
                Path(temporary_directory)
                / relative_publication["url"].split("https://data.example.test/", 1)[1]
            ).with_suffix(".html")
            html = relative_page.read_text(encoding="utf-8")
            self.assertIn(
                '<meta name="twitter:card" content="summary_large_image">',
                html,
            )
            self.assertIn("window.location.replace(", html)
            self.assertIn(relative_publication["live_url"].replace("&", "&amp;"), html)

            image = relative_page.with_suffix(".png")
            png = image.read_bytes()
            width, height = struct.unpack(">II", png[16:24])
            self.assertEqual((width, height), (IMAGE_WIDTH, IMAGE_HEIGHT))


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


def _sandbox_cards() -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    start = datetime(2026, 7, 20, 14, 5, tzinfo=timezone.utc)
    rate_rows = [
        {
            "observed_date": (start + timedelta(days=index)).isoformat(),
            "median_usd_per_hour": 0.08 + index * 0.002,
            "p25_usd_per_hour": 0.06 + index * 0.001,
            "p75_usd_per_hour": 0.11 + index * 0.003,
        }
        for index in range(10)
    ]
    rates: dict[str, object] = {
        "schema_version": "compute_bazaar_card_v1",
        "card_type": "compute_rate_market",
        "card_id": "sandbox:rates",
        "as_of": rate_rows[-1]["observed_date"],
        "series": {"sandbox": rate_rows, "vm": [], "combined": []},
        "headline": {"sandbox_median": rate_rows[-1]["median_usd_per_hour"]},
    }
    workload: dict[str, object] = {
        "schema_version": "compute_bazaar_card_v1",
        "card_type": "sandbox_workload",
        "card_id": "sandbox:workload",
        "as_of": (start + timedelta(days=9)).isoformat(),
        "headline": {
            "median_estimated_cost_usd": 0.031,
            "median_runtime_seconds": 184.0,
            "observed_at": (start + timedelta(days=9)).isoformat(),
        },
        "series": [],
        "data": {
            "workload": {
                "service_summary": [
                    {
                        "series_id": f"sandbox-{index}",
                        "median_estimated_cost_usd": 0.02 + index * 0.004,
                        "p25_estimated_cost_usd": 0.018 + index * 0.003,
                        "p75_estimated_cost_usd": 0.024 + index * 0.005,
                        "median_runtime_seconds": 150 + index * 20,
                        "p25_runtime_seconds": 140 + index * 18,
                        "p75_runtime_seconds": 165 + index * 22,
                    }
                    for index in range(6)
                ]
            }
        },
    }
    relative_rows = []
    for index in range(10):
        observed_at = start + timedelta(days=index)
        relative_rows.append(
            {
                "observed_at": observed_at.isoformat(),
                "common_start_at": start.isoformat(),
                "gpu_base_100": 100 + index,
                "gpu_p25_base_100": 98 + index,
                "gpu_p75_base_100": 102 + index,
                "vm_base_100": 100 + index * 0.25,
                "vm_p25_base_100": 99 + index * 0.2,
                "vm_p75_base_100": 101 + index * 0.3,
                "sandbox_base_100": 100 + index * 0.1,
                "sandbox_p25_base_100": 99 + index * 0.05,
                "sandbox_p75_base_100": 101 + index * 0.15,
            }
        )
    relative: dict[str, object] = {
        "schema_version": "compute_bazaar_card_v1",
        "card_type": "compute_relative_prices",
        "card_id": "market:relative-prices",
        "as_of": relative_rows[-1]["observed_at"],
        "series": relative_rows,
    }
    return rates, workload, relative


if __name__ == "__main__":
    unittest.main()
