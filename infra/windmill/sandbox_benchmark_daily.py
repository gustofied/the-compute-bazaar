"""Windmill script for daily public sandbox benchmark source ingestion."""

from __future__ import annotations

import json
import os
import subprocess


def main(
    source_repository: str = "starslingdev/hpc-sandbox-benchmarks",
    source_ref: str = "main",
    lake_root: str | None = None,
    aws_region: str = "eu-west-3",
) -> dict[str, object]:
    """Ingest the latest compatible public StarSling dataset."""
    output_root = _sandbox_output_root(lake_root)
    command = [
        "/opt/compute-bazaar/.venv/bin/sandbox-cost",
        "refresh-benchmark",
        "--output-root",
        output_root,
        "--source-repository",
        source_repository,
        "--source-ref",
        source_ref,
        "--publish-operational",
    ]
    env = os.environ.copy()
    env["AWS_REGION"] = aws_region
    env["AWS_DEFAULT_REGION"] = aws_region
    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    source_refresh = json.loads(completed.stdout)

    return {
        "output_root": output_root,
        "aws_region": aws_region,
        "source_repository": source_repository,
        "source_refresh": source_refresh,
        "gold_pickup": (
            "The next hourly market run reads the operational workload "
            "manifest and rebuilds sandbox gold/public JSON."
        ),
    }


def _sandbox_output_root(lake_root: str | None) -> str:
    if lake_root:
        return f"{lake_root.rstrip('/')}/sandbox_cost"
    return "data/lake/sandbox_cost"
