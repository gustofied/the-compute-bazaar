"""Command line entry points for GPU price ingestion and querying."""

from __future__ import annotations

import argparse
import json
import os
from typing import Any

from .datafusion import DEFAULT_BENCHMARK_SQL, query_parquet
from .pipeline import ingest_vast
from .schemas import to_jsonable


def main() -> None:
    parser = argparse.ArgumentParser(prog="gpu-prices")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest = subparsers.add_parser("ingest-vast", help="Fetch Vast offers and publish/store them")
    ingest.add_argument("--api-key", default=os.getenv("VAST_API_KEY"))
    ingest.add_argument("--api-base")
    ingest.add_argument("--query", help="Vast query string or JSON object")
    ingest.add_argument("--raw-root", default=os.getenv("COMPUTE_BAZAAR_RAW_ROOT", "data/raw"))
    ingest.add_argument("--lake-root", default=os.getenv("COMPUTE_BAZAAR_LAKE_ROOT", "data/lake"))
    ingest.add_argument("--automq-bootstrap-servers", default=os.getenv("AUTOMQ_BOOTSTRAP_SERVERS"))
    ingest.add_argument("--topic-prefix", default=os.getenv("COMPUTE_BAZAAR_TOPIC_PREFIX", "gpu"))
    ingest.add_argument("--run-id")
    ingest.add_argument("--trace-id")
    ingest.add_argument("--dry-run", action="store_true", help="Skip AutoMQ and keep publishing in memory")

    query = subparsers.add_parser("query", help="Run DataFusion SQL over a Parquet dataset")
    query.add_argument("--parquet", required=True)
    query.add_argument("--table", default="gpu_offers")
    query.add_argument("--sql", required=True)

    benchmark = subparsers.add_parser("benchmark", help="Run the default GPU benchmark query")
    benchmark.add_argument("--parquet", required=True)

    args = parser.parse_args()

    if args.command == "ingest-vast":
        result = ingest_vast(
            api_key=args.api_key,
            query=_parse_query(args.query),
            raw_root=args.raw_root,
            lake_root=args.lake_root,
            automq_bootstrap_servers=args.automq_bootstrap_servers,
            topic_prefix=args.topic_prefix,
            dry_run=args.dry_run,
            run_id=args.run_id,
            trace_id=args.trace_id,
            api_base=args.api_base,
        )
        _print_json(result.to_dict())
        return

    if args.command == "query":
        rows = query_parquet(parquet_uri=args.parquet, table_name=args.table, sql=args.sql)
        _print_json(rows)
        return

    if args.command == "benchmark":
        rows = query_parquet(
            parquet_uri=args.parquet,
            table_name="gpu_offers",
            sql=DEFAULT_BENCHMARK_SQL,
        )
        _print_json(rows)
        return


def _parse_query(value: str | None) -> str | dict[str, Any] | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    if stripped.startswith("{"):
        return json.loads(stripped)
    return stripped


def _print_json(value: Any) -> None:
    print(json.dumps(to_jsonable(value), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

