from __future__ import annotations

import unittest

from the_compute_bazaar.prices.public_view_capacity import akash_capacity_view


class AkashCapacityViewTest(unittest.TestCase):
    def test_keeps_gpu_and_cpu_capacity_separate_and_converts_cpu_to_vcpu(self):
        rows = [
            {
                "observed_at": "2026-08-16T05:00:00+00:00",
                "resource_type": "ALL_GPU",
                "total_units": 450,
                "rented_units": 100,
                "available_units": 340,
                "pending_units": 10,
                "rented_share": 100 / 450,
                "available_share": 340 / 450,
            },
            {
                "observed_at": "2026-08-16T06:00:00+00:00",
                "resource_type": "ALL_GPU",
                "total_units": 458,
                "rented_units": 94,
                "available_units": 354,
                "pending_units": 10,
                "rented_share": 94 / 458,
                "available_share": 354 / 458,
            },
            {
                "observed_at": "2026-08-16T06:00:00+00:00",
                "resource_type": "ALL_CPU",
                "total_units": 16_702_509,
                "rented_units": 3_200_000,
                "available_units": 13_289_264,
                "pending_units": 213_245,
                "rented_share": 3_200_000 / 16_702_509,
                "available_share": 13_289_264 / 16_702_509,
            },
            {
                "observed_at": "2026-08-16T06:00:00+00:00",
                "resource_type": "H100",
                "total_units": 99,
                "available_units": 80,
            },
        ]

        view = akash_capacity_view(
            manifest={"run_id": "gold-market-test"},
            rows=rows,
        )

        self.assertEqual(view["card_type"], "akash_capacity_history")
        self.assertEqual([row["resource_id"] for row in view["resources"]], ["GPU", "CPU"])
        gpu, cpu = view["resources"]
        self.assertEqual(len(gpu["history"]), 2)
        self.assertEqual(gpu["current"]["available"], 354)
        self.assertAlmostEqual(cpu["current"]["total"], 16_702.509)
        self.assertAlmostEqual(cpu["current"]["available"], 13_289.264)
        self.assertEqual(cpu["unit"], "vCPU")
        self.assertNotIn("H100", str(view))


if __name__ == "__main__":
    unittest.main()
