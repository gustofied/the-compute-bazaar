"""One command-line interface for Compute Bazaar data and operations."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from .api import create_app
from .cli_output import available_formats, render_table_payload, supports_auto_table
from .data_root import resolve_lake_root
from .market_query_service import MarketQueryService
from .prices.market_catalog import MarketDataCatalog
from .prices.schemas import to_jsonable
from .sandbox_cost.evidence import validate_evidence
from .sandbox_cost.pipeline import build_sandbox_cost
from .sandbox_cost.refresh import refresh_benchmark_sources
from .sandbox_cost.status import check_public_payload_freshness


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    selection = resolve_lake_root(args.lake_root)
    args.lake_root = selection.root
    payload = dispatch(args, parser=parser)
    if payload is not None:
        if args.command != "sandbox" and isinstance(payload, dict):
            payload = {
                "data_source": selection.to_dict(),
                **_compact_cli_run(payload),
            }
        serializable = to_jsonable(payload)
        output_format = args.output_format
        if output_format == "auto":
            output_format = (
                "table"
                if sys.stdout.isatty() and supports_auto_table(args.command)
                else "json"
            )
        if output_format == "table" and isinstance(serializable, dict):
            print(render_table_payload(serializable, command=args.command))
        else:
            print(json.dumps(serializable, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="compute-bazaar")
    parser.add_argument(
        "--lake-root",
        default=None,
        help="Local or s3:// root containing the manifested lake",
    )
    parser.add_argument(
        "--format",
        dest="output_format",
        choices=tuple(available_formats()),
        default="auto",
        help="Output format; auto uses tables in an interactive terminal",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("manifest", help="Show the latest public-safe Gold manifest")
    commands.add_parser("catalog", help="List saved DataFusion queries")
    commands.add_parser("tables", help="List Silver and Gold tables")

    describe = commands.add_parser("describe", help="Describe one catalog table")
    describe.add_argument("table")

    saved_query = commands.add_parser("query", help="Run one saved DataFusion query")
    saved_query.add_argument("query_id")
    saved_query.add_argument("--version")
    saved_query.add_argument("--limit", type=_positive_limit, default=100)

    scratch = commands.add_parser(
        "sql", help="Run bounded read-only SQL over Silver and Gold"
    )
    scratch.add_argument("statement", nargs="?")
    scratch.add_argument("--file", type=Path)
    scratch.add_argument("--limit", type=_positive_limit, default=100)

    price_index = commands.add_parser("price-index", help="Read GPU Price Index values")
    price_index.add_argument("--family")
    price_index.add_argument(
        "--history",
        action="store_true",
        help="Read retained hourly index snapshots; --limit selects run count",
    )
    price_index.add_argument("--limit", type=_positive_limit, default=20)

    availability = commands.add_parser(
        "availability", help="Read GPU Availability observations"
    )
    availability.add_argument("--gpu-model")
    availability.add_argument("--measurement-kind")
    availability.add_argument("--history", action="store_true")
    availability.add_argument("--limit", type=_positive_limit, default=100)

    listings = commands.add_parser("listings", help="Read normalized Gold listings")
    listings.add_argument("--gpu-model")
    listings.add_argument("--provider")
    listings.add_argument("--limit", type=_positive_limit, default=100)

    providers = commands.add_parser("providers", help="Compare providers")
    providers.add_argument("--gpu-model")
    providers.add_argument("--limit", type=_positive_limit, default=100)

    prime = commands.add_parser("prime", help="Read the Prime offer market")
    prime.add_argument("--family")

    api = commands.add_parser("api", help="Serve the read-only query API")
    api.add_argument("--host", default="127.0.0.1")
    api.add_argument("--port", type=int, default=8766)
    api.add_argument(
        "--enable-scratch-sql",
        action="store_true",
        help="Expose the bounded SQL endpoint; disabled by default",
    )

    sandbox = commands.add_parser("sandbox", help="Maintain StarSling workload costs")
    sandbox_commands = sandbox.add_subparsers(dest="sandbox_command", required=True)
    sandbox_build = sandbox_commands.add_parser(
        "build",
        help="Build Bronze, Silver, Gold, and optional public data",
    )
    sandbox_build.add_argument("--output-root", default="data/sandbox-cost")
    sandbox_build.add_argument("--dashboard-output-root")
    sandbox_build.add_argument("--workload-benchmark-manifest-ref")

    sandbox_commands.add_parser("validate", help="Validate canonical evidence")

    refresh = sandbox_commands.add_parser(
        "refresh",
        help="Fetch public StarSling runs and detect new compatible rows",
    )
    refresh.add_argument("--output-root", default="data/sandbox-cost")
    refresh.add_argument("--source-ref", default="main")
    refresh.add_argument(
        "--source-repository",
        default="starslingdev/hpc-sandbox-benchmarks",
    )
    refresh.add_argument("--check", action="store_true")
    refresh.add_argument("--update-evidence", action="store_true")
    refresh.add_argument("--publish-operational", action="store_true")

    check_public = sandbox_commands.add_parser(
        "check-public",
        help="Validate the public measured-workload payload",
    )
    check_public.add_argument("--url", required=True)
    check_public.add_argument("--max-age-hours", type=float, default=24 * 8)
    return parser


def dispatch(args: argparse.Namespace, *, parser: argparse.ArgumentParser) -> Any:
    if args.command == "api":
        import uvicorn

        uvicorn.run(
            create_app(
                lake_root=args.lake_root,
                enable_scratch_sql=args.enable_scratch_sql,
            ),
            host=args.host,
            port=args.port,
        )
        return None
    if args.command == "sandbox":
        return _run_sandbox(args, parser=parser)

    if args.command in {"tables", "describe", "sql"}:
        catalog = MarketDataCatalog(lake_root=args.lake_root)
        if args.command == "tables":
            return catalog.tables()
        if args.command == "describe":
            return catalog.describe(args.table)
        return catalog.query(
            _read_sql_statement(args, parser=parser),
            limit=args.limit,
        )

    service = MarketQueryService(lake_root=args.lake_root)
    if args.command == "manifest":
        return service.manifest()
    if args.command == "catalog":
        return service.catalog()
    if args.command == "query":
        return service.saved_query(
            query_id=args.query_id,
            version=args.version,
            limit=args.limit,
        )
    if args.command == "price-index":
        return service.gpu_price_index(
            family=args.family,
            history=args.history,
            limit=args.limit,
        )
    if args.command == "availability":
        return service.gpu_availability(
            gpu_model=args.gpu_model,
            measurement_kind=args.measurement_kind,
            history=args.history,
            limit=args.limit,
        )
    if args.command == "listings":
        return service.listings(
            gpu_model=args.gpu_model,
            provider=args.provider,
            limit=args.limit,
        )
    if args.command == "providers":
        return service.providers(gpu_model=args.gpu_model, limit=args.limit)
    if args.command == "prime":
        return service.prime_offers(family=args.family)
    raise AssertionError(f"Unhandled command: {args.command}")


def _run_sandbox(args: argparse.Namespace, *, parser: argparse.ArgumentParser) -> Any:
    if args.sandbox_command == "build":
        return asdict(
            build_sandbox_cost(
                output_root=args.output_root,
                dashboard_output_root=args.dashboard_output_root,
                workload_benchmark_manifest_ref=args.workload_benchmark_manifest_ref,
            )
        )
    if args.sandbox_command == "validate":
        return validate_evidence()
    if args.sandbox_command == "refresh":
        if args.check and args.update_evidence:
            parser.error("--check and --update-evidence cannot be used together")
        result = refresh_benchmark_sources(
            output_root=args.output_root,
            source_ref=args.source_ref,
            source_repository=args.source_repository,
            update_evidence=args.update_evidence,
            publish_operational=args.publish_operational,
        )
        if args.check and result["changed"]:
            _print_before_exit(result, status=1)
        return result
    if args.sandbox_command == "check-public":
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
        if result["status"] != "ok":
            _print_before_exit(result, status=1)
        return result
    raise AssertionError(f"Unhandled sandbox command: {args.sandbox_command}")


def _read_sql_statement(
    args: argparse.Namespace,
    *,
    parser: argparse.ArgumentParser,
) -> str:
    if args.statement and args.file:
        parser.error(
            "Provide SQL as an argument, through --file, or on stdin; choose one"
        )
    if args.file:
        return args.file.read_text(encoding="utf-8")
    if args.statement:
        return args.statement
    if sys.stdin.isatty():
        parser.error("SQL is required as an argument, through --file, or on stdin")
    return sys.stdin.read()


def _positive_limit(value: str) -> int:
    parsed = int(value)
    if not 1 <= parsed <= 1000:
        raise argparse.ArgumentTypeError("limit must be between 1 and 1000")
    return parsed


def _compact_cli_run(payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    run = result.get("run")
    if isinstance(run, dict):
        result["run"] = {
            field: run.get(field)
            for field in ("run_id", "observed_at")
            if run.get(field) is not None
        }
    return result


def _print_before_exit(payload: Any, *, status: int) -> None:
    print(json.dumps(to_jsonable(payload), indent=2, sort_keys=True))
    raise SystemExit(status)


if __name__ == "__main__":
    main()
