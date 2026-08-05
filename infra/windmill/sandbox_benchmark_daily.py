"""Windmill script for daily public sandbox benchmark source ingestion."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from the_compute_bazaar.sandbox_cost.refresh import refresh_benchmark_sources


def main(
    source_repository: str = "starslingdev/hpc-sandbox-benchmarks",
    source_ref: str = "main",
    lake_root: str | None = None,
    aws_region: str = "eu-west-3",
) -> dict[str, object]:
    """Ingest the latest compatible public StarSling dataset."""
    output_root = _sandbox_output_root(lake_root)
    with _temporary_aws_region(aws_region):
        source_refresh = refresh_benchmark_sources(
            output_root=output_root,
            source_repository=source_repository,
            source_ref=source_ref,
            publish_operational=True,
        )

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


@contextmanager
def _temporary_aws_region(region: str) -> Iterator[None]:
    keys = ("AWS_REGION", "AWS_DEFAULT_REGION")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        for key in keys:
            os.environ[key] = region
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
