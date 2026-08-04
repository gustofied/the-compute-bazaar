"""Compatibility launcher for the shared Compute Bazaar evaluation viewer."""

from __future__ import annotations

from pathlib import Path
import sys


BENCH_ROOT = Path(__file__).resolve().parents[3]
if str(BENCH_ROOT) not in sys.path:
    sys.path.insert(0, str(BENCH_ROOT))

from viewer.app import (  # noqa: E402
    ASSET_ROOT,
    _discover_run_paths,
    _evaluation_summary,
    _evals_html,
    _index_html,
    _runs_html,
    create_app,
    main,
)

__all__ = [
    "ASSET_ROOT",
    "_discover_run_paths",
    "_evaluation_summary",
    "_evals_html",
    "_index_html",
    "_runs_html",
    "create_app",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
