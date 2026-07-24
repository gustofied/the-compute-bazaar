"""CLI for the recurring sandbox-cost benchmark."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from .pipeline import (
    GOLD_QUERIES,
    build_sandbox_cost,
    query_sandbox_gold,
    validate_evidence,
)
from .refresh import refresh_benchmark_sources


def main() -> None:
    parser = argparse.ArgumentParser(prog="sandbox-cost")
    commands = parser.add_subparsers(dest="command", required=True)

    build = commands.add_parser(
        "build",
        help="Build bronze, silver, gold, and optional public snapshot data",
    )
    build.add_argument("--output-root", default="data/sandbox-cost")
    build.add_argument("--dashboard-output-root")
    build.add_argument("--gpu-history-ref")

    commands.add_parser("validate", help="Validate canonical source evidence")

    refresh = commands.add_parser(
        "refresh-benchmark",
        help="Fetch public StarSling runs into bronze and detect new comparable rows",
    )
    refresh.add_argument("--output-root", default="data/sandbox-cost")
    refresh.add_argument("--source-ref", default="main")
    refresh.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero when public benchmark evidence has changed",
    )
    refresh.add_argument(
        "--update-evidence",
        action="store_true",
        help="Update versioned normalized evidence after a reviewed refresh",
    )

    query = commands.add_parser(
        "query",
        help="Run an allowlisted DataFusion query over sandbox gold",
    )
    query.add_argument("--output-root", default="data/sandbox-cost")
    query.add_argument("--query", choices=sorted(GOLD_QUERIES), required=True)
    query.add_argument("--limit", type=int)

    args = parser.parse_args()
    if args.command == "build":
        result = build_sandbox_cost(
            output_root=args.output_root,
            dashboard_output_root=args.dashboard_output_root,
            gpu_history_ref=args.gpu_history_ref,
        )
        print(json.dumps(asdict(result), indent=2, sort_keys=True))
        return
    if args.command == "validate":
        print(json.dumps(validate_evidence(), indent=2, sort_keys=True))
        return
    if args.command == "refresh-benchmark":
        if args.check and args.update_evidence:
            parser.error("--check and --update-evidence cannot be used together")
        result = refresh_benchmark_sources(
            output_root=args.output_root,
            source_ref=args.source_ref,
            update_evidence=args.update_evidence,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        if args.check and result["changed"]:
            raise SystemExit(1)
        return
    if args.command == "query":
        print(
            json.dumps(
                query_sandbox_gold(
                    output_root=args.output_root,
                    query_id=args.query,
                    limit=args.limit,
                ),
                indent=2,
                sort_keys=True,
                default=str,
            )
        )
        return
    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    main()
