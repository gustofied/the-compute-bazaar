import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from the_compute_bazaar.dashboard import (
    _available_snapshots,
    _read_snapshot,
    _resolve_snapshot_source,
    _snapshot_name_for_filename,
)


class DashboardSnapshotTests(unittest.TestCase):
    def test_local_snapshot_read_is_allowlisted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "manifest.json").write_text(json.dumps({"run_id": "demo"}), encoding="utf-8")

            self.assertEqual(_available_snapshots(root), ["manifest"])
            self.assertEqual(_read_snapshot(root, "manifest"), {"run_id": "demo"})

    def test_snapshot_file_route_rejects_unknown_files(self) -> None:
        self.assertEqual(_snapshot_name_for_filename("latest-index.json"), "latest-index")
        self.assertEqual(_snapshot_name_for_filename("index-history.json"), "index-history")
        with self.assertRaises(HTTPException):
            _snapshot_name_for_filename("../manifest.json")
        with self.assertRaises(HTTPException):
            _snapshot_name_for_filename("secret.json")

    def test_auto_source_prefers_s3_when_prefix_is_configured(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "COMPUTE_BAZAAR_DASHBOARD_SOURCE": "",
                "COMPUTE_BAZAAR_DASHBOARD_S3_PREFIX": "",
                "COMPUTE_BAZAAR_DASHBOARD_OUTPUT_ROOT": "",
            },
            clear=False,
        ):
            self.assertEqual(_resolve_snapshot_source("auto", "s3://bucket/dashboard/compute-bazaar"), "s3")
            self.assertEqual(_resolve_snapshot_source("auto", None), "local")
            self.assertEqual(_resolve_snapshot_source("local", "s3://bucket/dashboard/compute-bazaar"), "local")


if __name__ == "__main__":
    unittest.main()
