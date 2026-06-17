"""Windmill-compatible Vast ingestion function."""

from __future__ import annotations

import os
from typing import Any

from ..automq import kafka_bootstrap_servers_from_env
from ..pipeline import ingest_vast


def main(
    api_key: str | None = None,
    query: str | dict[str, Any] | None = None,
    raw_root: str | None = None,
    lake_root: str | None = None,
    automq_bootstrap_servers: str | None = None,
    topic_prefix: str = "gpu",
    dry_run: bool = False,
    run_id: str | None = None,
    trace_id: str | None = None,
    api_base: str | None = None,
) -> dict[str, Any]:
    result = ingest_vast(
        api_key=api_key or os.getenv("VAST_API_KEY"),
        query=query,
        raw_root=raw_root or os.getenv("COMPUTE_BAZAAR_RAW_ROOT", "data/raw"),
        lake_root=lake_root or os.getenv("COMPUTE_BAZAAR_LAKE_ROOT", "data/lake"),
        automq_bootstrap_servers=automq_bootstrap_servers or kafka_bootstrap_servers_from_env(),
        topic_prefix=topic_prefix,
        dry_run=dry_run,
        run_id=run_id,
        trace_id=trace_id,
        api_base=api_base,
    )
    return result.to_dict()
