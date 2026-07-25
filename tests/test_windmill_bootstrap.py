import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.error import HTTPError


WINDMILL_DIR = Path(__file__).parents[1] / "infra" / "windmill"
sys.path.insert(0, str(WINDMILL_DIR))

from bootstrap_provider_schedule import WindmillClient  # noqa: E402
from bootstrap_sandbox_benchmark_schedule import schedule_args  # noqa: E402
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

    def test_sandbox_schedule_keeps_provider_credentials_out_of_windmill(
        self,
    ) -> None:
        args = schedule_args(
            "compute-bazaar",
            source_ref="main",
            dispatch=True,
            providers="e2b,daytona-vm",
            suites="realworld",
            replicas="12",
            pts_passes="",
        )

        self.assertEqual(
            args["github_token"],
            "$var:f/compute-bazaar/sandbox_benchmark_github_token",
        )
        self.assertNotIn("e2b_api_key", args)
        self.assertNotIn("daytona_api_key", args)
        self.assertNotIn("modal_token_secret", args)

    def test_daily_script_publishes_operational_source_before_dispatch(
        self,
    ) -> None:
        completed = SimpleNamespace(
            stdout='{"operational_manifest_ref":"s3://bucket/latest.json"}'
        )
        with (
            patch.object(
                sandbox_benchmark_daily.subprocess,
                "run",
                return_value=completed,
            ) as run,
            patch.object(
                sandbox_benchmark_daily,
                "_dispatch_benchmark",
                return_value={"requested": True},
            ) as dispatch,
        ):
            result = sandbox_benchmark_daily.main(
                source_repository="owner/benchmark",
                lake_root="s3://bucket/lake",
                dispatch_repository="owner/benchmark",
                github_token="secret",
                dispatch=True,
            )

        command = run.call_args.args[0]
        self.assertIn("--publish-operational", command)
        self.assertIn("s3://bucket/lake/sandbox_cost", command)
        self.assertNotIn("secret", command)
        dispatch.assert_called_once()
        self.assertTrue(result["dispatch"]["requested"])

    def test_daily_script_requires_dispatch_token(self) -> None:
        completed = SimpleNamespace(stdout="{}")
        with patch.object(
            sandbox_benchmark_daily.subprocess,
            "run",
            return_value=completed,
        ):
            with self.assertRaisesRegex(ValueError, "github_token"):
                sandbox_benchmark_daily.main(
                    source_repository="owner/benchmark",
                    lake_root="s3://bucket/lake",
                    dispatch_repository="owner/benchmark",
                    dispatch=True,
                )

    def test_dispatch_rejects_invalid_replica_count_before_http(self) -> None:
        with (
            patch.object(sandbox_benchmark_daily, "urlopen") as urlopen,
            self.assertRaisesRegex(ValueError, "replicas must be"),
        ):
            sandbox_benchmark_daily._dispatch_benchmark(
                repository="owner/benchmark",
                workflow_id="bench-matrix.yml",
                ref="main",
                token="secret",
                providers="e2b",
                suites="realworld",
                replicas="",
                pts_passes="",
            )

        urlopen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
