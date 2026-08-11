"""Render an opaque Transactions DOCX set and record deterministic QA inputs."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


def render_one(
    document: Path,
    output_root: Path,
    python: Path,
    renderer: Path,
) -> tuple[str, dict[str, Any]]:
    review_id = document.stem
    output_dir = output_root / review_id
    completed = subprocess.run(
        [
            str(python),
            str(renderer),
            str(document),
            "--output_dir",
            str(output_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    pages = sorted(output_dir.glob("page-*.png"))
    return review_id, {
        "document_sha256": sha256(document),
        "status": "ok" if completed.returncode == 0 and pages else "failed",
        "return_code": completed.returncode,
        "page_count": len(pages),
        "page_paths": [page.relative_to(output_root).as_posix() for page in pages],
        "stdout": completed.stdout[-4000:],
        "stderr": completed.stderr[-4000:],
    }


def sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--python", required=True, type=Path)
    parser.add_argument("--renderer", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    documents = sorted(args.input_dir.resolve().glob("*.docx"))
    if not documents:
        raise RuntimeError("blind input directory has no DOCX files")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    records: dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = {
            executor.submit(
                render_one,
                document,
                args.output_dir.resolve(),
                args.python.resolve(),
                args.renderer.resolve(),
            ): document
            for document in documents
        }
        for future in as_completed(futures):
            review_id, record = future.result()
            records[review_id] = record
            print(
                f"{review_id}: {record['status']} ({record['page_count']} pages)",
                flush=True,
            )

    manifest = {
        "schema_version": "compute-bazaar-bench.transactions.blind-render.v1",
        "documents": dict(sorted(records.items())),
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    failures = sum(record["status"] != "ok" for record in records.values())
    print(f"rendered={len(records)} failures={failures}")
    return 0 if failures == 0 else 3


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"blind render error: {exc}", file=sys.stderr)
        raise SystemExit(2)
