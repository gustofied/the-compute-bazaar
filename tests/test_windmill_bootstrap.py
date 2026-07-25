import sys
import unittest
from pathlib import Path
from unittest.mock import Mock
from urllib.error import HTTPError


WINDMILL_DIR = Path(__file__).parents[1] / "infra" / "windmill"
sys.path.insert(0, str(WINDMILL_DIR))

from bootstrap_provider_schedule import WindmillClient  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
