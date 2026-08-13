from __future__ import annotations

import unittest

from infra.aws.check_public_market import _validate_publication_manifest
from the_compute_bazaar.prices.publication_profiles import (
    GPU_PUBLICATION_RENDER_PROFILE,
    PRIME_PUBLICATION_RENDER_PROFILE,
    WORKLOAD_PUBLICATION_RENDER_PROFILE,
)


class PublicationFreshnessTest(unittest.TestCase):
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
