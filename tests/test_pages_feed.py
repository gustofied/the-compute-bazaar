from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from the_compute_bazaar.pages_feed import (
    _restore_publication_archive,
    _save_publication_archive,
    prepare_pages_site,
)


class PagesFeedTest(unittest.TestCase):
    def test_publication_archive_survives_a_fresh_site_build(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "archive"
            old_page = archive / "gpu-index/h200/7-day/old.html"
            old_page.parent.mkdir(parents=True)
            old_page.write_text("old", encoding="utf-8")
            output = root / "site"
            output.mkdir()

            _restore_publication_archive(
                output=output,
                publication_archive_root=archive,
            )
            new_page = output / "publications/gpu-index/h200/7-day/new.html"
            new_page.parent.mkdir(parents=True, exist_ok=True)
            new_page.write_text("new", encoding="utf-8")
            _save_publication_archive(
                output=output,
                publication_archive_root=archive,
            )

            self.assertEqual(
                (output / "publications/gpu-index/h200/7-day/old.html").read_text(),
                "old",
            )
            self.assertEqual(
                (archive / "gpu-index/h200/7-day/new.html").read_text(),
                "new",
            )

    def test_prepares_pages_metadata_snapshots_and_pretty_routes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "site"
            publication = output / "publications/gpu-index/h100/7-day/revision.html"
            publication.parent.mkdir(parents=True)
            publication.write_text("<h1>H100</h1>", encoding="utf-8")
            snapshots = root / "snapshots"
            snapshot = snapshots / "gpu-benchmark/h100.json"
            snapshot.parent.mkdir(parents=True)
            snapshot.write_text('{"gpu":"H100"}', encoding="utf-8")

            result = prepare_pages_site(
                output_root=output,
                static_snapshot_root=snapshots,
                custom_domain="bazaar.example",
            )

            self.assertTrue((output / ".nojekyll").exists())
            self.assertEqual(
                (output / "CNAME").read_text(encoding="utf-8"),
                "bazaar.example\n",
            )
            self.assertTrue((output / "index.html").exists())
            self.assertEqual(
                (
                    output / "publications/gpu-index/h100/7-day/revision/index.html"
                ).read_text(encoding="utf-8"),
                "<h1>H100</h1>",
            )
            self.assertEqual(
                (output / "api/dashboard-snapshots/gpu-benchmark/h100.json").read_text(
                    encoding="utf-8"
                ),
                '{"gpu":"H100"}',
            )
            self.assertEqual(result["static_snapshot_count"], 1)
            self.assertEqual(result["pretty_publication_route_count"], 1)


if __name__ == "__main__":
    unittest.main()
