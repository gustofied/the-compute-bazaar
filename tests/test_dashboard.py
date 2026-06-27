import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from the_compute_bazaar.dashboard import (
    _available_snapshots,
    _infer_dashboard_s3_prefix_from_lake,
    _read_snapshot,
    _resolve_snapshot_source,
    _snapshot_s3_prefix,
    _snapshot_name_for_filename,
    create_app,
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
                "COMPUTE_BAZAAR_LAKE_ROOT": "",
            },
            clear=False,
        ):
            self.assertEqual(_resolve_snapshot_source("auto", "s3://bucket/dashboard/compute-bazaar"), "s3")
            self.assertEqual(_resolve_snapshot_source("auto", None), "local")
            self.assertEqual(_resolve_snapshot_source("local", "s3://bucket/dashboard/compute-bazaar"), "local")

    def test_auto_source_infers_s3_dashboard_prefix_from_s3_lake_root(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "COMPUTE_BAZAAR_DASHBOARD_SOURCE": "",
                "COMPUTE_BAZAAR_DASHBOARD_S3_PREFIX": "",
                "COMPUTE_BAZAAR_DASHBOARD_OUTPUT_ROOT": "",
                "COMPUTE_BAZAAR_LAKE_ROOT": "s3://bucket/lake",
            },
            clear=False,
        ):
            self.assertEqual(_snapshot_s3_prefix(None), "s3://bucket/dashboard/compute-bazaar")
            self.assertEqual(_resolve_snapshot_source("auto", None), "s3")

    def test_s3_dashboard_prefix_inference_supports_nested_lake_root(self) -> None:
        self.assertEqual(
            _infer_dashboard_s3_prefix_from_lake("s3://bucket/project/lake"),
            "s3://bucket/project/dashboard/compute-bazaar",
        )
        self.assertIsNone(_infer_dashboard_s3_prefix_from_lake("s3://bucket/warehouse"))
        self.assertIsNone(_infer_dashboard_s3_prefix_from_lake("data/lake"))

    def test_explicit_local_dashboard_output_disables_s3_inference(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "COMPUTE_BAZAAR_DASHBOARD_SOURCE": "",
                "COMPUTE_BAZAAR_DASHBOARD_S3_PREFIX": "",
                "COMPUTE_BAZAAR_DASHBOARD_OUTPUT_ROOT": "data/dashboard/compute-bazaar",
                "COMPUTE_BAZAAR_LAKE_ROOT": "s3://bucket/lake",
            },
            clear=False,
        ):
            self.assertIsNone(_snapshot_s3_prefix(None))
            self.assertEqual(_resolve_snapshot_source("auto", None), "local")

    def test_operator_routes_are_registered(self) -> None:
        app = create_app()

        paths = {route.path for route in app.routes}

        self.assertIn("/operator/", paths)
        self.assertIn("/api/operator/queries", paths)
        self.assertIn("/api/operator/queries/{query_id}", paths)
        self.assertIn("/api/operator/lineage", paths)
        self.assertIn("/api/operator/sql", paths)
        self.assertIn("/api/operator/ref-preview", paths)


if __name__ == "__main__":
    unittest.main()
