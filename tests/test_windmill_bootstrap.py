import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.error import HTTPError


WINDMILL_DIR = Path(__file__).parents[1] / "infra" / "windmill"
sys.path.insert(0, str(WINDMILL_DIR))

from bootstrap_provider_schedule import WindmillClient  # noqa: E402
from bootstrap_market_schedule import (  # noqa: E402
    schedule_args as market_schedule_args,
)
from bootstrap_sandbox_benchmark_schedule import schedule_args  # noqa: E402
import market_hourly  # noqa: E402
import sandbox_benchmark_daily  # noqa: E402


class WindmillScheduleTests(unittest.TestCase):
    def test_upsert_schedule_uses_dedicated_enabled_endpoint(self) -> None:
        client = WindmillClient(
            base_url="http://windmill.test",
            workspace="compute-bazaar",
            token="test-token",
        )
        conflict = HTTPError(
            url="http://windmill.test/api/schedule",
            code=409,
            msg="already exists",
            hdrs=None,
            fp=None,
        )
        post = Mock(side_effect=[conflict, b"", b""])
        client._post = post

        client.upsert_schedule(
            path="f/compute-bazaar/vast_hourly_hourly",
            script_path="f/compute-bazaar/vast_hourly",
            schedule="0 0 * * * *",
            timezone="UTC",
            enabled=False,
            summary="Vast debug schedule",
            description="Manual debugging only",
            args={},
        )

        self.assertEqual(post.call_count, 3)
        self.assertIn("/schedules/update/", post.call_args_list[1].args[0])
        self.assertIn("/schedules/setenabled/", post.call_args_list[2].args[0])
        self.assertEqual(post.call_args_list[2].args[1], {"enabled": False})
        self.assertEqual(post.call_args_list[2].kwargs["ok_statuses"], {200})

    def test_sandbox_schedule_is_source_only(self) -> None:
        args = schedule_args(
            "compute-bazaar",
            source_ref="main",
            aws_region="eu-west-3",
        )

        self.assertEqual(
            args,
            {
                "source_repository": (
                    "$var:f/compute-bazaar/sandbox_benchmark_source_repository"
                ),
                "source_ref": "main",
                "lake_root": "$var:f/compute-bazaar/lake_root",
                "aws_region": "eu-west-3",
            },
        )

    def test_market_schedule_passes_canonical_public_base_variable(self) -> None:
        args = market_schedule_args(
            "compute-bazaar",
            dashboard_limit=100,
            lium_size=200,
            lium_max_pages=10,
            lium_paginate=True,
        )

        self.assertEqual(
            args["public_base_url"],
            "$var:f/compute-bazaar/public_base_url",
        )

    def test_market_script_exports_public_base_to_cli_environment(self) -> None:
        completed = SimpleNamespace(stdout="{}")
        with patch.object(
            market_hourly.subprocess,
            "run",
            return_value=completed,
        ) as run:
            market_hourly.main(
                public_base_url="https://bazaar.adamsioud.com",
            )

        self.assertEqual(
            run.call_args.kwargs["env"]["COMPUTE_BAZAAR_PUBLIC_BASE_URL"],
            "https://bazaar.adamsioud.com",
        )

    def test_daily_script_publishes_operational_source(self) -> None:
        completed = SimpleNamespace(
            stdout='{"operational_manifest_ref":"s3://bucket/latest.json"}'
        )
        with patch.object(
            sandbox_benchmark_daily.subprocess,
            "run",
            return_value=completed,
        ) as run:
            result = sandbox_benchmark_daily.main(
                source_repository="owner/benchmark",
                lake_root="s3://bucket/lake",
                aws_region="eu-west-3",
            )

        command = run.call_args.args[0]
        self.assertIn("--publish-operational", command)
        self.assertIn("s3://bucket/lake/sandbox_cost", command)
        self.assertNotIn("github", " ".join(command).lower())
        self.assertEqual(
            run.call_args.kwargs["env"]["AWS_DEFAULT_REGION"],
            "eu-west-3",
        )
        self.assertEqual(
            result["source_refresh"]["operational_manifest_ref"],
            "s3://bucket/latest.json",
        )


if __name__ == "__main__":
    unittest.main()
