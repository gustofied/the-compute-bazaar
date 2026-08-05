"""CLI for the recurring sandbox-cost benchmark."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from urllib.request import Request, urlopen

from .pipeline import (
    build_sandbox_cost,
    check_public_payload_freshness,
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
    build.add_argument("--workload-benchmark-manifest-ref")

    commands.add_parser("validate", help="Validate canonical source evidence")

    refresh = commands.add_parser(
        "refresh-benchmark",
        help="Fetch public StarSling runs into bronze and detect new comparable rows",
    )
    refresh.add_argument("--output-root", default="data/sandbox-cost")
    refresh.add_argument("--source-ref", default="main")
    refresh.add_argument(
        "--source-repository",
        default="starslingdev/hpc-sandbox-benchmarks",
        help="GitHub owner/repository containing the StarSling dataset",
    )
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
    refresh.add_argument(
        "--publish-operational",
        action="store_true",
        help=(
            "Publish validated source results as the operational silver "
            "generation consumed by the next gold build"
        ),
    )

    check_public = commands.add_parser(
        "check-public",
        help="Validate the public measured-workload snapshot",
    )
    check_public.add_argument("--url", required=True)
    check_public.add_argument("--max-age-hours", type=float, default=2.5)

    args = parser.parse_args()
    if args.command == "build":
        result = build_sandbox_cost(
            output_root=args.output_root,
            dashboard_output_root=args.dashboard_output_root,
            workload_benchmark_manifest_ref=args.workload_benchmark_manifest_ref,
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
            source_repository=args.source_repository,
            update_evidence=args.update_evidence,
            publish_operational=args.publish_operational,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        if args.check and result["changed"]:
            raise SystemExit(1)
        return
    if args.command == "check-public":
        request = Request(
            args.url,
            headers={"User-Agent": "the-compute-bazaar-freshness-check/1"},
        )
        with urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        result = check_public_payload_freshness(
            payload,
            max_age_hours=args.max_age_hours,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        if result["status"] != "ok":
            raise SystemExit(1)
        return
    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    main()
