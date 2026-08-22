from __future__ import annotations

import unittest

from infra.aws.check_public_market import (
    _validate_market_cohort,
    _validate_publication_manifest,
)
from the_compute_bazaar.prices.publication_profiles import (
    GPU_PUBLICATION_RENDER_PROFILE,
    PRIME_PUBLICATION_RENDER_PROFILE,
    WORKLOAD_PUBLICATION_RENDER_PROFILE,
)
from the_compute_bazaar.prices.public_view_capacity import akash_capacity_view


class PublicationFreshnessTest(unittest.TestCase):
    def test_akash_snapshot_separates_gpu_and_cpu_capacity(self) -> None:
        view = akash_capacity_view(
            manifest={"run_id": "gold-market-test"},
            rows=[
                {
                    "observed_at": "2026-08-21T16:00:00+00:00",
                    "resource_type": "ALL_GPU",
                    "total_units": 450,
                    "rented_units": 100,
                    "available_units": 340,
                },
                {
                    "observed_at": "2026-08-21T16:00:00+00:00",
                    "resource_type": "ALL_CPU",
                    "total_units": 16_702_509,
                    "available_units": 13_289_264,
                },
            ],
        )

        gpu, cpu = view["resources"]
        self.assertEqual(view["status"], "frozen")
        self.assertEqual(gpu["current"]["available"], 340)
        self.assertAlmostEqual(cpu["current"]["available"], 13_289.264)

    def test_degraded_optional_provider_is_healthy_with_quorum(self) -> None:
        market_run = {
            "providers": [*(f"provider-{index}" for index in range(12)), "optional"],
            "successful_providers": [f"provider-{index}" for index in range(12)],
            "failed_providers": ["optional"],
            "data_quality": {
                "cohort": {
                    "status": "degraded",
                    "minimum_successful_providers": 12,
                    "required_providers": [],
                }
            },
        }

        providers, failed, status = _validate_market_cohort(
            market_run,
            required_providers=set(),
            forbidden_providers=set(),
            minimum_provider_count=12,
        )

        self.assertEqual(len(providers), 12)
        self.assertEqual(failed, {"optional"})
        self.assertEqual(status, "degraded")

    def test_publication_policy_cannot_claim_a_one_provider_quorum(self) -> None:
        market_run = {
            "providers": [f"provider-{index}" for index in range(12)],
            "successful_providers": [f"provider-{index}" for index in range(12)],
            "failed_providers": [],
            "data_quality": {
                "cohort": {
                    "status": "complete",
                    "minimum_successful_providers": 1,
                    "required_providers": [],
                }
            },
        }

        with self.assertRaisesRegex(RuntimeError, "publication policy"):
            _validate_market_cohort(
                market_run,
                required_providers=set(),
                forbidden_providers=set(),
                minimum_provider_count=12,
            )

    def test_retired_provider_is_rejected_even_when_its_read_failed(self) -> None:
        market_run = {
            "providers": [*(f"provider-{index}" for index in range(12)), "retired"],
            "successful_providers": [f"provider-{index}" for index in range(12)],
            "failed_providers": ["retired"],
            "data_quality": {
                "cohort": {
                    "status": "degraded",
                    "minimum_successful_providers": 12,
                    "required_providers": [],
                }
            },
        }

        with self.assertRaisesRegex(RuntimeError, "Retired providers"):
            _validate_market_cohort(
                market_run,
                required_providers=set(),
                forbidden_providers={"retired"},
                minimum_provider_count=12,
            )

    def test_card_families_have_distinct_content_profiles(self) -> None:
        profiles = {
            GPU_PUBLICATION_RENDER_PROFILE,
            PRIME_PUBLICATION_RENDER_PROFILE,
            WORKLOAD_PUBLICATION_RENDER_PROFILE,
        }

        self.assertEqual(len(profiles), 3)
        for profile in profiles:
            self.assertRegex(profile, r"^social_png_rgb_1200x630_.+_[0-9a-f]{12}$")

    def test_manifest_must_match_deployed_revision(self) -> None:
        manifest = {
            "render_profile": GPU_PUBLICATION_RENDER_PROFILE,
            "renderer_revision": "a" * 40,
            "publication_count": 12,
        }

        with self.assertRaisesRegex(RuntimeError, "expected"):
            _validate_publication_manifest(
                manifest,
                label="GPU",
                expected_profile=GPU_PUBLICATION_RENDER_PROFILE,
                expected_count=12,
                required_renderer_revision="b" * 40,
            )

    def test_manifest_must_match_content_profile(self) -> None:
        manifest = {
            "render_profile": "old-renderer",
            "renderer_revision": "a" * 40,
            "publication_count": 12,
        }

        with self.assertRaisesRegex(RuntimeError, "render profile"):
            _validate_publication_manifest(
                manifest,
                label="GPU",
                expected_profile=GPU_PUBLICATION_RENDER_PROFILE,
                expected_count=12,
                required_renderer_revision=None,
            )


if __name__ == "__main__":
    unittest.main()
