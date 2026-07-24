"""Command line entry points for GPU price ingestion and querying."""

from __future__ import annotations

import argparse
import json
import os
from typing import Any

from .automq import (
    check_cluster,
    kafka_bootstrap_servers_from_env,
    kafka_config_from_env,
)
from .checks import run_stage1_checks
from .coverage import query_frontier_coverage
from .datafusion import DEFAULT_BENCHMARK_SQL, query_parquet, query_price_index
from .gold import (
    build_gold_market_tables,
    export_gold_dashboard_snapshot,
    query_gold_benchmark_constituents,
    query_gold_benchmark_values,
    query_gold_index_constituents,
    query_gold_index_quality,
    query_gold_listings,
    query_gold_price_index,
    query_gold_provider_comparison,
    read_latest_gold_manifest,
)
from .manifest import read_latest_manifest
from .market_run import (
    default_market_providers,
    list_market_runs,
    read_latest_market_run,
    run_market_hourly,
    write_dashboard_market_run_snapshots,
)
from .operator import (
    list_operator_queries,
    preview_operator_ref,
    run_operator_query,
    run_operator_sql,
)
from .pipeline import (
    ingest_akash,
    ingest_aws_spot,
    ingest_azure_retail,
    ingest_clore,
    ingest_digitalocean,
    ingest_gpus_io,
    ingest_hyperstack,
    ingest_inference_sh,
    ingest_lambda_cloud,
    ingest_lium,
    ingest_prime_intellect,
    ingest_rate_card,
    ingest_runpod,
    ingest_sesterce,
    ingest_shadeform,
    ingest_spheron,
    ingest_tensordock,
    ingest_verda,
    ingest_vast,
)
from .providers.rate_cards import DEFAULT_RATE_CARD_PROVIDER, rate_card_providers
from .schemas import to_jsonable


def main() -> None:
    _load_local_env()

    parser = argparse.ArgumentParser(prog="gpu-prices")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest = subparsers.add_parser(
        "ingest-vast", help="Fetch Vast offers and publish/store them"
    )
    ingest.add_argument("--api-key", default=os.getenv("VAST_API_KEY"))
    ingest.add_argument("--api-base")
    ingest.add_argument("--query", help="Vast query string or JSON object")
    ingest.add_argument(
        "--raw-root", default=os.getenv("COMPUTE_BAZAAR_RAW_ROOT", "data/raw")
    )
    ingest.add_argument(
        "--lake-root", default=os.getenv("COMPUTE_BAZAAR_LAKE_ROOT", "data/lake")
    )
    ingest.add_argument(
        "--automq-bootstrap-servers", default=kafka_bootstrap_servers_from_env()
    )
    ingest.add_argument(
        "--topic-prefix", default=os.getenv("COMPUTE_BAZAAR_TOPIC_PREFIX", "gpu")
    )
    ingest.add_argument("--run-id")
    ingest.add_argument("--trace-id")
    ingest.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip AutoMQ and keep publishing in memory",
    )

    ingest_lium_parser = subparsers.add_parser(
        "ingest-lium", help="Fetch Lium executors and publish/store them"
    )
    ingest_lium_parser.add_argument("--api-key", default=os.getenv("LIUM_API_KEY"))
    ingest_lium_parser.add_argument("--api-base")
    ingest_lium_parser.add_argument("--query", help="Lium query JSON object")
    ingest_lium_parser.add_argument("--page", type=int)
    ingest_lium_parser.add_argument("--size", type=int, default=200)
    ingest_lium_parser.add_argument(
        "--paginate", action="store_true", help="Fetch Lium pages until exhausted"
    )
    ingest_lium_parser.add_argument("--max-pages", type=int, default=10)
    ingest_lium_parser.add_argument(
        "--raw-root", default=os.getenv("COMPUTE_BAZAAR_RAW_ROOT", "data/raw")
    )
    ingest_lium_parser.add_argument(
        "--lake-root", default=os.getenv("COMPUTE_BAZAAR_LAKE_ROOT", "data/lake")
    )
    ingest_lium_parser.add_argument(
        "--automq-bootstrap-servers", default=kafka_bootstrap_servers_from_env()
    )
    ingest_lium_parser.add_argument(
        "--topic-prefix", default=os.getenv("COMPUTE_BAZAAR_TOPIC_PREFIX", "gpu")
    )
    ingest_lium_parser.add_argument("--run-id")
    ingest_lium_parser.add_argument("--trace-id")
    ingest_lium_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip AutoMQ and keep publishing in memory",
    )

    ingest_aws_spot_parser = subparsers.add_parser(
        "ingest-aws-spot",
        help="Fetch current AWS EC2 Spot prices for frontier GPU instances",
    )
    ingest_aws_spot_parser.add_argument("--regions", help="Comma-separated AWS regions")
    _add_ingest_storage_args(ingest_aws_spot_parser)

    ingest_azure_parser = subparsers.add_parser(
        "ingest-azure-retail",
        help="Fetch current Azure frontier GPU VM rates from the public retail-prices API",
    )
    ingest_azure_parser.add_argument("--prices-url")
    ingest_azure_parser.add_argument("--max-pages-per-sku", type=int, default=10)
    _add_ingest_storage_args(ingest_azure_parser)

    ingest_prime_parser = subparsers.add_parser(
        "ingest-prime-intellect",
        help="Fetch live Prime Intellect frontier GPU availability",
    )
    ingest_prime_parser.add_argument(
        "--api-key", default=os.getenv("PRIME_INTELLECT_API_KEY")
    )
    ingest_prime_parser.add_argument("--api-base")
    ingest_prime_parser.add_argument("--max-pages-per-gpu", type=int, default=20)
    _add_ingest_storage_args(ingest_prime_parser)

    ingest_spheron_parser = subparsers.add_parser(
        "ingest-spheron",
        help="Fetch Spheron's public live multi-provider GPU offers",
    )
    ingest_spheron_parser.add_argument("--offers-url")
    _add_ingest_storage_args(ingest_spheron_parser)

    ingest_inference_sh_parser = subparsers.add_parser(
        "ingest-inference-sh",
        help="Fetch Inference.sh's public available cross-cloud GPU catalog",
    )
    ingest_inference_sh_parser.add_argument("--api-base")
    _add_ingest_storage_args(ingest_inference_sh_parser)

    ingest_gpus_io_parser = subparsers.add_parser(
        "ingest-gpus-io",
        help="Fetch GPUs.io's authenticated live multi-provider price feed",
    )
    ingest_gpus_io_parser.add_argument(
        "--api-key",
        default=os.getenv("GPUS_IO_API_KEY"),
    )
    ingest_gpus_io_parser.add_argument("--api-base")
    ingest_gpus_io_parser.add_argument("--max-pages", type=int, default=20)
    ingest_gpus_io_parser.add_argument("--page-size", type=int, default=200)
    _add_ingest_storage_args(ingest_gpus_io_parser)

    ingest_akash_parser = subparsers.add_parser(
        "ingest-akash",
        help="Fetch Akash's public live GPU pricing and availability summary",
    )
    ingest_akash_parser.add_argument("--prices-url")
    _add_ingest_storage_args(ingest_akash_parser)

    ingest_shadeform_parser = subparsers.add_parser(
        "ingest-shadeform",
        help="Fetch live Shadeform multi-cloud GPU inventory",
    )
    ingest_shadeform_parser.add_argument(
        "--api-key", default=os.getenv("SHADEFORM_API_KEY")
    )
    ingest_shadeform_parser.add_argument("--api-base")
    _add_ingest_storage_args(ingest_shadeform_parser)

    ingest_sesterce_parser = subparsers.add_parser(
        "ingest-sesterce",
        help="Fetch live Sesterce GPU Cloud offers",
    )
    ingest_sesterce_parser.add_argument(
        "--api-key", default=os.getenv("SESTERCE_API_KEY")
    )
    ingest_sesterce_parser.add_argument("--api-base")
    _add_ingest_storage_args(ingest_sesterce_parser)

    ingest_runpod_parser = subparsers.add_parser(
        "ingest-runpod",
        help="Fetch live RunPod GPU type prices and stock",
    )
    ingest_runpod_parser.add_argument("--api-key", default=os.getenv("RUNPOD_API_KEY"))
    ingest_runpod_parser.add_argument("--graphql-url")
    _add_ingest_storage_args(ingest_runpod_parser)

    ingest_clore_parser = subparsers.add_parser(
        "ingest-clore",
        help="Fetch Clore.ai's public live GPU marketplace",
    )
    ingest_clore_parser.add_argument("--marketplace-url")
    _add_ingest_storage_args(ingest_clore_parser)

    ingest_verda_parser = subparsers.add_parser(
        "ingest-verda",
        help="Fetch Verda's public GPU catalog and optional authenticated live availability",
    )
    ingest_verda_parser.add_argument(
        "--client-id", default=os.getenv("VERDA_CLIENT_ID")
    )
    ingest_verda_parser.add_argument(
        "--client-secret", default=os.getenv("VERDA_CLIENT_SECRET")
    )
    ingest_verda_parser.add_argument(
        "--access-token", default=os.getenv("VERDA_ACCESS_TOKEN")
    )
    ingest_verda_parser.add_argument("--api-base")
    _add_ingest_storage_args(ingest_verda_parser)

    ingest_tensordock_parser = subparsers.add_parser(
        "ingest-tensordock",
        help="Fetch TensorDock live hostnode GPU stock and component prices",
    )
    ingest_tensordock_parser.add_argument(
        "--api-key", default=os.getenv("TENSORDOCK_API_KEY")
    )
    ingest_tensordock_parser.add_argument("--api-base")
    _add_ingest_storage_args(ingest_tensordock_parser)

    ingest_hyperstack_parser = subparsers.add_parser(
        "ingest-hyperstack",
        help="Fetch Hyperstack real-time GPU stock and current pricebook",
    )
    ingest_hyperstack_parser.add_argument(
        "--api-key", default=os.getenv("HYPERSTACK_API_KEY")
    )
    ingest_hyperstack_parser.add_argument("--api-base")
    _add_ingest_storage_args(ingest_hyperstack_parser)

    ingest_lambda_parser = subparsers.add_parser(
        "ingest-lambda-cloud",
        help="Fetch Lambda Cloud live instance pricing and capacity regions",
    )
    ingest_lambda_parser.add_argument(
        "--api-key", default=os.getenv("LAMBDA_CLOUD_API_KEY")
    )
    ingest_lambda_parser.add_argument("--api-base")
    _add_ingest_storage_args(ingest_lambda_parser)

    ingest_digitalocean_parser = subparsers.add_parser(
        "ingest-digitalocean",
        help="Fetch DigitalOcean live GPU Droplet sizes and regions",
    )
    ingest_digitalocean_parser.add_argument(
        "--api-token", default=os.getenv("DIGITALOCEAN_API_TOKEN")
    )
    ingest_digitalocean_parser.add_argument("--api-base")
    ingest_digitalocean_parser.add_argument("--max-pages", type=int, default=10)
    _add_ingest_storage_args(ingest_digitalocean_parser)

    ingest_rate_card_parser = subparsers.add_parser(
        "ingest-rate-card",
        help="Ingest official published provider rate cards as benchmark observations",
    )
    ingest_rate_card_parser.add_argument(
        "--provider",
        choices=[DEFAULT_RATE_CARD_PROVIDER, *rate_card_providers()],
        default=DEFAULT_RATE_CARD_PROVIDER,
    )
    ingest_rate_card_parser.add_argument(
        "--raw-root", default=os.getenv("COMPUTE_BAZAAR_RAW_ROOT", "data/raw")
    )
    ingest_rate_card_parser.add_argument(
        "--lake-root", default=os.getenv("COMPUTE_BAZAAR_LAKE_ROOT", "data/lake")
    )
    ingest_rate_card_parser.add_argument(
        "--automq-bootstrap-servers", default=kafka_bootstrap_servers_from_env()
    )
    ingest_rate_card_parser.add_argument(
        "--topic-prefix", default=os.getenv("COMPUTE_BAZAAR_TOPIC_PREFIX", "gpu")
    )
    ingest_rate_card_parser.add_argument("--run-id")
    ingest_rate_card_parser.add_argument("--trace-id")
    ingest_rate_card_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip AutoMQ and keep publishing in memory",
    )

    query = subparsers.add_parser(
        "query", help="Run DataFusion SQL over a Parquet dataset"
    )
    query.add_argument("--parquet", required=True)
    query.add_argument("--table", default="gpu_offers")
    query.add_argument("--sql", required=True)

    benchmark = subparsers.add_parser(
        "benchmark", help="Run the default GPU benchmark query"
    )
    benchmark.add_argument("--parquet", required=True)

    latest_manifest = subparsers.add_parser(
        "latest-manifest", help="Print the latest GPU offer manifest"
    )
    latest_manifest.add_argument(
        "--lake-root", default=os.getenv("COMPUTE_BAZAAR_LAKE_ROOT", "data/lake")
    )
    latest_manifest.add_argument("--provider", default="vast")

    latest_index = subparsers.add_parser(
        "latest-index", help="Run the Stage 1 price index over latest offers"
    )
    latest_index.add_argument(
        "--lake-root", default=os.getenv("COMPUTE_BAZAAR_LAKE_ROOT", "data/lake")
    )
    latest_index.add_argument("--provider", default="vast")
    latest_index.add_argument("--limit", type=int, default=25)

    build_gold = subparsers.add_parser(
        "build-gold", help="Build gold market tables from latest silver offers"
    )
    build_gold.add_argument(
        "--lake-root", default=os.getenv("COMPUTE_BAZAAR_LAKE_ROOT", "data/lake")
    )
    build_gold.add_argument("--provider", default="vast")
    build_gold.add_argument(
        "--providers", help="Comma-separated provider scope, e.g. vast,lium"
    )
    build_gold.add_argument("--run-id")

    latest_gold_manifest = subparsers.add_parser(
        "latest-gold-manifest", help="Print the latest gold manifest"
    )
    latest_gold_manifest.add_argument(
        "--lake-root", default=os.getenv("COMPUTE_BAZAAR_LAKE_ROOT", "data/lake")
    )

    gold_index = subparsers.add_parser(
        "gold-index", help="Query the latest gold price index table"
    )
    gold_index.add_argument(
        "--lake-root", default=os.getenv("COMPUTE_BAZAAR_LAKE_ROOT", "data/lake")
    )
    gold_index.add_argument("--limit", type=int, default=25)

    gold_index_constituents = subparsers.add_parser(
        "gold-index-constituents",
        help="Query the latest gold index constituents table",
    )
    gold_index_constituents.add_argument(
        "--lake-root", default=os.getenv("COMPUTE_BAZAAR_LAKE_ROOT", "data/lake")
    )
    gold_index_constituents.add_argument("--gpu-model")
    gold_index_constituents.add_argument("--limit", type=int, default=100)

    gold_index_quality = subparsers.add_parser(
        "gold-index-quality",
        help="Summarize candidate/included/excluded index constituents by GPU product",
    )
    gold_index_quality.add_argument(
        "--lake-root", default=os.getenv("COMPUTE_BAZAAR_LAKE_ROOT", "data/lake")
    )
    gold_index_quality.add_argument("--limit", type=int, default=100)

    gold_benchmarks = subparsers.add_parser(
        "gold-benchmarks",
        help="Query the latest H100/H200/B200/B300 benchmark values",
    )
    gold_benchmarks.add_argument(
        "--lake-root", default=os.getenv("COMPUTE_BAZAAR_LAKE_ROOT", "data/lake")
    )
    gold_benchmarks.add_argument("--limit", type=int, default=25)

    gold_benchmark_constituents = subparsers.add_parser(
        "gold-benchmark-constituents",
        help="Query listing constituents behind benchmark values",
    )
    gold_benchmark_constituents.add_argument(
        "--lake-root", default=os.getenv("COMPUTE_BAZAAR_LAKE_ROOT", "data/lake")
    )
    gold_benchmark_constituents.add_argument(
        "--benchmark-family-id", choices=["H100", "H200", "B200", "B300"]
    )
    gold_benchmark_constituents.add_argument("--limit", type=int, default=100)

    frontier_coverage = subparsers.add_parser(
        "frontier-coverage",
        help="Measure fresh H100/H200/B200/B300 observation coverage against a target",
    )
    frontier_coverage.add_argument(
        "--lake-root", default=os.getenv("COMPUTE_BAZAAR_LAKE_ROOT", "data/lake")
    )
    frontier_coverage.add_argument("--target", type=int, default=50)
    frontier_coverage.add_argument("--capacity-target", type=int, default=50)
    frontier_coverage.add_argument("--observation-target", type=int, default=50)

    gold_index_history = subparsers.add_parser(
        "gold-index-history",
        help="Query recent gold price index values as a time series",
    )
    gold_index_history.add_argument(
        "--lake-root", default=os.getenv("COMPUTE_BAZAAR_LAKE_ROOT", "data/lake")
    )
    gold_index_history.add_argument("--history-limit", type=int, default=48)
    gold_index_history.add_argument(
        "--gpu-models", help="Comma-separated GPU products to include"
    )

    gold_listings = subparsers.add_parser(
        "gold-listings", help="Query the latest gold listing table"
    )
    gold_listings.add_argument(
        "--lake-root", default=os.getenv("COMPUTE_BAZAAR_LAKE_ROOT", "data/lake")
    )
    gold_listings.add_argument("--gpu-model")
    gold_listings.add_argument("--limit", type=int, default=25)

    gold_provider_comparison = subparsers.add_parser(
        "gold-provider-comparison",
        help="Compare provider floors from the latest gold listing table",
    )
    gold_provider_comparison.add_argument(
        "--lake-root", default=os.getenv("COMPUTE_BAZAAR_LAKE_ROOT", "data/lake")
    )
    gold_provider_comparison.add_argument("--gpu-model")
    gold_provider_comparison.add_argument("--limit", type=int, default=50)

    operator_queries = subparsers.add_parser(
        "operator-queries",
        help="List cataloged operator/Curia DataFusion SQL queries",
    )
    operator_queries.add_argument(
        "--lake-root", default=os.getenv("COMPUTE_BAZAAR_LAKE_ROOT", "data/lake")
    )

    operator_query = subparsers.add_parser(
        "operator-query",
        help="Run a cataloged operator/Curia DataFusion SQL query",
    )
    operator_query.add_argument("query_id")
    operator_query.add_argument(
        "--lake-root", default=os.getenv("COMPUTE_BAZAAR_LAKE_ROOT", "data/lake")
    )
    operator_query.add_argument("--version")
    operator_query.add_argument("--limit", type=int)

    operator_sql = subparsers.add_parser(
        "operator-sql",
        help="Run read-only scratch SQL over latest gold tables through DataFusion",
    )
    operator_sql.add_argument(
        "--lake-root", default=os.getenv("COMPUTE_BAZAAR_LAKE_ROOT", "data/lake")
    )
    operator_sql.add_argument("--sql", help="Read-only SELECT/WITH SQL to run")
    operator_sql.add_argument("--sql-file", help="Path to a SQL file to run")
    operator_sql.add_argument("--limit", type=int, default=100)

    operator_ref_preview = subparsers.add_parser(
        "operator-ref-preview",
        help="Preview an allowed ref from the latest operator manifest chain",
    )
    operator_ref_preview.add_argument("ref")
    operator_ref_preview.add_argument(
        "--lake-root", default=os.getenv("COMPUTE_BAZAAR_LAKE_ROOT", "data/lake")
    )
    operator_ref_preview.add_argument("--max-bytes", type=int, default=65536)

    export_gold_dashboard = subparsers.add_parser(
        "export-gold-dashboard",
        help="Export gold query snapshots as JSON for static D3/blog consumers",
    )
    export_gold_dashboard.add_argument(
        "--lake-root", default=os.getenv("COMPUTE_BAZAAR_LAKE_ROOT", "data/lake")
    )
    export_gold_dashboard.add_argument(
        "--output-root",
        default=os.getenv(
            "COMPUTE_BAZAAR_DASHBOARD_OUTPUT_ROOT", "data/dashboard/compute-bazaar"
        ),
    )
    export_gold_dashboard.add_argument("--limit", type=int, default=100)

    market_hourly = subparsers.add_parser(
        "market-hourly", help="Run provider ingest, gold build, dashboard export"
    )
    market_hourly.add_argument(
        "--raw-root", default=os.getenv("COMPUTE_BAZAAR_RAW_ROOT", "data/raw")
    )
    market_hourly.add_argument(
        "--lake-root", default=os.getenv("COMPUTE_BAZAAR_LAKE_ROOT", "data/lake")
    )
    market_hourly.add_argument(
        "--dashboard-output-root",
        default=os.getenv(
            "COMPUTE_BAZAAR_DASHBOARD_OUTPUT_ROOT", "data/dashboard/compute-bazaar"
        ),
    )
    market_hourly.add_argument(
        "--providers", default=",".join(default_market_providers())
    )
    market_hourly.add_argument(
        "--automq-bootstrap-servers", default=kafka_bootstrap_servers_from_env()
    )
    market_hourly.add_argument(
        "--topic-prefix", default=os.getenv("COMPUTE_BAZAAR_TOPIC_PREFIX", "gpu")
    )
    market_hourly.add_argument("--run-id")
    market_hourly.add_argument("--dashboard-limit", type=int, default=100)
    market_hourly.add_argument("--lium-size", type=int, default=200)
    market_hourly.add_argument("--lium-max-pages", type=int, default=10)
    market_hourly.add_argument("--no-lium-pagination", action="store_true")
    market_hourly.add_argument(
        "--dry-run", action="store_true", help="Skip AutoMQ publishing"
    )

    latest_market_run = subparsers.add_parser(
        "latest-market-run", help="Print the latest market run manifest"
    )
    latest_market_run.add_argument(
        "--lake-root", default=os.getenv("COMPUTE_BAZAAR_LAKE_ROOT", "data/lake")
    )

    market_runs = subparsers.add_parser(
        "market-runs", help="List recent market run manifests"
    )
    market_runs.add_argument(
        "--lake-root", default=os.getenv("COMPUTE_BAZAAR_LAKE_ROOT", "data/lake")
    )
    market_runs.add_argument("--limit", type=int, default=24)

    automq_check = subparsers.add_parser(
        "automq-check", help="Verify AutoMQ/Kafka connectivity"
    )
    automq_check.add_argument(
        "--bootstrap-servers", default=kafka_bootstrap_servers_from_env()
    )

    stage1_check = subparsers.add_parser(
        "stage1-check", help="Verify Stage 1 ingestion/query/orchestration health"
    )
    stage1_check.add_argument(
        "--lake-root", default=os.getenv("COMPUTE_BAZAAR_LAKE_ROOT", "data/lake")
    )
    stage1_check.add_argument("--provider", default="vast")
    stage1_check.add_argument(
        "--windmill-base-url", default=os.getenv("WINDMILL_BASE_URL")
    )
    stage1_check.add_argument(
        "--windmill-token",
        default=os.getenv("WINDMILL_TOKEN")
        or _read_optional_secret_file(".secrets/windmill-bootstrap-token.txt"),
    )
    stage1_check.add_argument(
        "--windmill-workspace",
        default=os.getenv("WINDMILL_WORKSPACE", "compute-bazaar"),
    )
    stage1_check.add_argument(
        "--check-automq",
        action="store_true",
        help="Also verify private AutoMQ connectivity; run this from a VPC-connected worker",
    )
    stage1_check.add_argument(
        "--require-ingest-env",
        action="store_true",
        help="Fail if provider/Kafka ingest secrets are not present in the local environment",
    )
    stage1_check.add_argument(
        "--windmill-schedule-path",
        default=os.getenv(
            "WINDMILL_SCHEDULE_PATH", "f/compute-bazaar/market_hourly_hourly"
        ),
    )

    args = parser.parse_args()

    if args.command == "ingest-vast":
        result = ingest_vast(
            api_key=args.api_key,
            query=_parse_query(args.query),
            raw_root=args.raw_root,
            lake_root=args.lake_root,
            automq_bootstrap_servers=args.automq_bootstrap_servers,
            automq_config=kafka_config_from_env(),
            topic_prefix=args.topic_prefix,
            dry_run=args.dry_run,
            run_id=args.run_id,
            trace_id=args.trace_id,
            api_base=args.api_base,
        )
        _print_json(result.to_dict())
        return

    if args.command == "ingest-lium":
        query = _parse_query_object(args.query) or {}
        if args.page is not None:
            query["page"] = args.page
        if args.size is not None:
            query["size"] = args.size
        result = ingest_lium(
            api_key=args.api_key,
            query=query,
            raw_root=args.raw_root,
            lake_root=args.lake_root,
            automq_bootstrap_servers=args.automq_bootstrap_servers,
            automq_config=kafka_config_from_env(),
            topic_prefix=args.topic_prefix,
            dry_run=args.dry_run,
            run_id=args.run_id,
            trace_id=args.trace_id,
            api_base=args.api_base,
            paginate=args.paginate,
            max_pages=args.max_pages,
        )
        _print_json(result.to_dict())
        return

    if args.command == "ingest-aws-spot":
        result = ingest_aws_spot(
            regions=_parse_csv(args.regions),
            raw_root=args.raw_root,
            lake_root=args.lake_root,
            automq_bootstrap_servers=args.automq_bootstrap_servers,
            automq_config=kafka_config_from_env(),
            topic_prefix=args.topic_prefix,
            dry_run=args.dry_run,
            run_id=args.run_id,
            trace_id=args.trace_id,
        )
        _print_json(result.to_dict())
        return

    if args.command == "ingest-azure-retail":
        result = ingest_azure_retail(
            prices_url=args.prices_url,
            max_pages_per_sku=args.max_pages_per_sku,
            raw_root=args.raw_root,
            lake_root=args.lake_root,
            automq_bootstrap_servers=args.automq_bootstrap_servers,
            automq_config=kafka_config_from_env(),
            topic_prefix=args.topic_prefix,
            dry_run=args.dry_run,
            run_id=args.run_id,
            trace_id=args.trace_id,
        )
        _print_json(result.to_dict())
        return

    if args.command == "ingest-prime-intellect":
        result = ingest_prime_intellect(
            api_key=args.api_key,
            api_base=args.api_base,
            max_pages_per_gpu=args.max_pages_per_gpu,
            raw_root=args.raw_root,
            lake_root=args.lake_root,
            automq_bootstrap_servers=args.automq_bootstrap_servers,
            automq_config=kafka_config_from_env(),
            topic_prefix=args.topic_prefix,
            dry_run=args.dry_run,
            run_id=args.run_id,
            trace_id=args.trace_id,
        )
        _print_json(result.to_dict())
        return

    if args.command == "ingest-spheron":
        result = ingest_spheron(
            offers_url=args.offers_url,
            raw_root=args.raw_root,
            lake_root=args.lake_root,
            automq_bootstrap_servers=args.automq_bootstrap_servers,
            automq_config=kafka_config_from_env(),
            topic_prefix=args.topic_prefix,
            dry_run=args.dry_run,
            run_id=args.run_id,
            trace_id=args.trace_id,
        )
        _print_json(result.to_dict())
        return

    if args.command == "ingest-inference-sh":
        result = ingest_inference_sh(
            api_base=args.api_base,
            raw_root=args.raw_root,
            lake_root=args.lake_root,
            automq_bootstrap_servers=args.automq_bootstrap_servers,
            automq_config=kafka_config_from_env(),
            topic_prefix=args.topic_prefix,
            dry_run=args.dry_run,
            run_id=args.run_id,
            trace_id=args.trace_id,
        )
        _print_json(result.to_dict())
        return

    if args.command == "ingest-gpus-io":
        result = ingest_gpus_io(
            api_key=args.api_key,
            api_base=args.api_base,
            max_pages=args.max_pages,
            page_size=args.page_size,
            raw_root=args.raw_root,
            lake_root=args.lake_root,
            automq_bootstrap_servers=args.automq_bootstrap_servers,
            automq_config=kafka_config_from_env(),
            topic_prefix=args.topic_prefix,
            dry_run=args.dry_run,
            run_id=args.run_id,
            trace_id=args.trace_id,
        )
        _print_json(result.to_dict())
        return

    if args.command == "ingest-akash":
        result = ingest_akash(
            prices_url=args.prices_url,
            raw_root=args.raw_root,
            lake_root=args.lake_root,
            automq_bootstrap_servers=args.automq_bootstrap_servers,
            automq_config=kafka_config_from_env(),
            topic_prefix=args.topic_prefix,
            dry_run=args.dry_run,
            run_id=args.run_id,
            trace_id=args.trace_id,
        )
        _print_json(result.to_dict())
        return

    if args.command == "ingest-shadeform":
        result = ingest_shadeform(
            api_key=args.api_key,
            api_base=args.api_base,
            raw_root=args.raw_root,
            lake_root=args.lake_root,
            automq_bootstrap_servers=args.automq_bootstrap_servers,
            automq_config=kafka_config_from_env(),
            topic_prefix=args.topic_prefix,
            dry_run=args.dry_run,
            run_id=args.run_id,
            trace_id=args.trace_id,
        )
        _print_json(result.to_dict())
        return

    if args.command == "ingest-sesterce":
        result = ingest_sesterce(
            api_key=args.api_key,
            api_base=args.api_base,
            raw_root=args.raw_root,
            lake_root=args.lake_root,
            automq_bootstrap_servers=args.automq_bootstrap_servers,
            automq_config=kafka_config_from_env(),
            topic_prefix=args.topic_prefix,
            dry_run=args.dry_run,
            run_id=args.run_id,
            trace_id=args.trace_id,
        )
        _print_json(result.to_dict())
        return

    if args.command == "ingest-runpod":
        result = ingest_runpod(
            api_key=args.api_key,
            graphql_url=args.graphql_url,
            raw_root=args.raw_root,
            lake_root=args.lake_root,
            automq_bootstrap_servers=args.automq_bootstrap_servers,
            automq_config=kafka_config_from_env(),
            topic_prefix=args.topic_prefix,
            dry_run=args.dry_run,
            run_id=args.run_id,
            trace_id=args.trace_id,
        )
        _print_json(result.to_dict())
        return

    if args.command == "ingest-clore":
        result = ingest_clore(
            marketplace_url=args.marketplace_url,
            raw_root=args.raw_root,
            lake_root=args.lake_root,
            automq_bootstrap_servers=args.automq_bootstrap_servers,
            automq_config=kafka_config_from_env(),
            topic_prefix=args.topic_prefix,
            dry_run=args.dry_run,
            run_id=args.run_id,
            trace_id=args.trace_id,
        )
        _print_json(result.to_dict())
        return

    if args.command == "ingest-verda":
        result = ingest_verda(
            client_id=args.client_id,
            client_secret=args.client_secret,
            access_token=args.access_token,
            api_base=args.api_base,
            raw_root=args.raw_root,
            lake_root=args.lake_root,
            automq_bootstrap_servers=args.automq_bootstrap_servers,
            automq_config=kafka_config_from_env(),
            topic_prefix=args.topic_prefix,
            dry_run=args.dry_run,
            run_id=args.run_id,
            trace_id=args.trace_id,
        )
        _print_json(result.to_dict())
        return

    if args.command == "ingest-tensordock":
        result = ingest_tensordock(
            api_key=args.api_key,
            api_base=args.api_base,
            raw_root=args.raw_root,
            lake_root=args.lake_root,
            automq_bootstrap_servers=args.automq_bootstrap_servers,
            automq_config=kafka_config_from_env(),
            topic_prefix=args.topic_prefix,
            dry_run=args.dry_run,
            run_id=args.run_id,
            trace_id=args.trace_id,
        )
        _print_json(result.to_dict())
        return

    if args.command == "ingest-hyperstack":
        result = ingest_hyperstack(
            api_key=args.api_key,
            api_base=args.api_base,
            raw_root=args.raw_root,
            lake_root=args.lake_root,
            automq_bootstrap_servers=args.automq_bootstrap_servers,
            automq_config=kafka_config_from_env(),
            topic_prefix=args.topic_prefix,
            dry_run=args.dry_run,
            run_id=args.run_id,
            trace_id=args.trace_id,
        )
        _print_json(result.to_dict())
        return

    if args.command == "ingest-lambda-cloud":
        result = ingest_lambda_cloud(
            api_key=args.api_key,
            api_base=args.api_base,
            raw_root=args.raw_root,
            lake_root=args.lake_root,
            automq_bootstrap_servers=args.automq_bootstrap_servers,
            automq_config=kafka_config_from_env(),
            topic_prefix=args.topic_prefix,
            dry_run=args.dry_run,
            run_id=args.run_id,
            trace_id=args.trace_id,
        )
        _print_json(result.to_dict())
        return

    if args.command == "ingest-digitalocean":
        result = ingest_digitalocean(
            api_token=args.api_token,
            api_base=args.api_base,
            max_pages=args.max_pages,
            raw_root=args.raw_root,
            lake_root=args.lake_root,
            automq_bootstrap_servers=args.automq_bootstrap_servers,
            automq_config=kafka_config_from_env(),
            topic_prefix=args.topic_prefix,
            dry_run=args.dry_run,
            run_id=args.run_id,
            trace_id=args.trace_id,
        )
        _print_json(result.to_dict())
        return

    if args.command == "ingest-rate-card":
        result = ingest_rate_card(
            provider=args.provider,
            raw_root=args.raw_root,
            lake_root=args.lake_root,
            automq_bootstrap_servers=args.automq_bootstrap_servers,
            automq_config=kafka_config_from_env(),
            topic_prefix=args.topic_prefix,
            dry_run=args.dry_run,
            run_id=args.run_id,
            trace_id=args.trace_id,
        )
        _print_json(result.to_dict())
        return

    if args.command == "query":
        rows = query_parquet(
            parquet_uri=args.parquet, table_name=args.table, sql=args.sql
        )
        _print_json(rows)
        return

    if args.command == "latest-manifest":
        _print_json(read_latest_manifest(args.lake_root, provider=args.provider))
        return

    if args.command == "latest-index":
        manifest = read_latest_manifest(args.lake_root, provider=args.provider)
        normalized_ref = manifest.get("normalized_ref")
        if not normalized_ref:
            raise SystemExit("Latest manifest has no normalized_ref")
        rows = query_price_index(parquet_uri=str(normalized_ref), limit=args.limit)
        _print_json({"manifest": manifest, "rows": rows})
        return

    if args.command == "build-gold":
        result = build_gold_market_tables(
            lake_root=args.lake_root,
            provider=args.provider,
            providers=_parse_csv(args.providers),
            run_id=args.run_id,
        )
        _print_json(result.to_dict())
        return

    if args.command == "latest-gold-manifest":
        _print_json(read_latest_gold_manifest(args.lake_root))
        return

    if args.command == "gold-index":
        _print_json(query_gold_price_index(lake_root=args.lake_root, limit=args.limit))
        return

    if args.command == "gold-index-constituents":
        _print_json(
            query_gold_index_constituents(
                lake_root=args.lake_root,
                gpu_model=args.gpu_model,
                limit=args.limit,
            )
        )
        return

    if args.command == "gold-index-quality":
        _print_json(
            query_gold_index_quality(lake_root=args.lake_root, limit=args.limit)
        )
        return

    if args.command == "frontier-coverage":
        _print_json(
            query_frontier_coverage(
                lake_root=args.lake_root,
                target=args.target,
                capacity_target=args.capacity_target,
                observation_target=args.observation_target,
            )
        )
        return

    if args.command == "gold-benchmarks":
        _print_json(
            query_gold_benchmark_values(lake_root=args.lake_root, limit=args.limit)
        )
        return

    if args.command == "gold-benchmark-constituents":
        _print_json(
            query_gold_benchmark_constituents(
                lake_root=args.lake_root,
                benchmark_family_id=args.benchmark_family_id,
                limit=args.limit,
            )
        )
        return

    if args.command == "gold-index-history":
        from .gold import query_gold_index_history

        _print_json(
            query_gold_index_history(
                lake_root=args.lake_root,
                history_limit=args.history_limit,
                gpu_models=_parse_csv(args.gpu_models),
            )
        )
        return

    if args.command == "gold-listings":
        _print_json(
            query_gold_listings(
                lake_root=args.lake_root, gpu_model=args.gpu_model, limit=args.limit
            )
        )
        return

    if args.command == "gold-provider-comparison":
        _print_json(
            query_gold_provider_comparison(
                lake_root=args.lake_root,
                gpu_model=args.gpu_model,
                limit=args.limit,
            )
        )
        return

    if args.command == "operator-queries":
        _print_json(list_operator_queries(lake_root=args.lake_root))
        return

    if args.command == "operator-query":
        _print_json(
            run_operator_query(
                lake_root=args.lake_root,
                query_id=args.query_id,
                version=args.version,
                limit=args.limit,
            )
        )
        return

    if args.command == "operator-sql":
        sql = _read_sql_input(sql=args.sql, sql_file=args.sql_file)
        try:
            _print_json(
                run_operator_sql(lake_root=args.lake_root, sql=sql, limit=args.limit)
            )
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        return

    if args.command == "operator-ref-preview":
        _print_json(
            preview_operator_ref(
                lake_root=args.lake_root,
                ref=args.ref,
                max_bytes=args.max_bytes,
            )
        )
        return

    if args.command == "export-gold-dashboard":
        result = export_gold_dashboard_snapshot(
            lake_root=args.lake_root,
            output_root=args.output_root,
            limit=args.limit,
        )
        try:
            market_refs = write_dashboard_market_run_snapshots(
                lake_root=args.lake_root, output_root=args.output_root
            )
        except FileNotFoundError:
            market_refs = {}
        result["output_refs"].update(market_refs)
        _print_json(result)
        return

    if args.command == "market-hourly":
        _print_json(
            run_market_hourly(
                raw_root=args.raw_root,
                lake_root=args.lake_root,
                dashboard_output_root=args.dashboard_output_root,
                providers=_parse_csv(args.providers) or default_market_providers(),
                automq_bootstrap_servers=args.automq_bootstrap_servers,
                automq_config=kafka_config_from_env(),
                topic_prefix=args.topic_prefix,
                run_id=args.run_id,
                dashboard_limit=args.dashboard_limit,
                lium_size=args.lium_size,
                lium_paginate=not args.no_lium_pagination,
                lium_max_pages=args.lium_max_pages,
                dry_run=args.dry_run,
            ).to_dict()
        )
        return

    if args.command == "latest-market-run":
        _print_json(read_latest_market_run(args.lake_root))
        return

    if args.command == "market-runs":
        _print_json({"rows": list_market_runs(args.lake_root, limit=args.limit)})
        return

    if args.command == "automq-check":
        if not args.bootstrap_servers:
            raise SystemExit(
                "Missing --bootstrap-servers, COMPUTE_BAZAAR_KAFKA_BOOTSTRAP_SERVERS, "
                "or AUTOMQ_BOOTSTRAP_SERVERS"
            )
        topics = check_cluster(
            bootstrap_servers=args.bootstrap_servers,
            config=kafka_config_from_env(),
        )
        _print_json({"connected": True, "topics": topics})
        return

    if args.command == "benchmark":
        rows = query_parquet(
            parquet_uri=args.parquet,
            table_name="gpu_offers",
            sql=DEFAULT_BENCHMARK_SQL,
        )
        _print_json(rows)
        return

    if args.command == "stage1-check":
        _print_json(
            run_stage1_checks(
                lake_root=args.lake_root,
                provider=args.provider,
                check_automq=args.check_automq,
                require_ingest_env=args.require_ingest_env,
                windmill_base_url=args.windmill_base_url,
                windmill_token=args.windmill_token,
                windmill_workspace=args.windmill_workspace,
                windmill_schedule_path=args.windmill_schedule_path,
            )
        )
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


def _add_ingest_storage_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--raw-root", default=os.getenv("COMPUTE_BAZAAR_RAW_ROOT", "data/raw")
    )
    parser.add_argument(
        "--lake-root", default=os.getenv("COMPUTE_BAZAAR_LAKE_ROOT", "data/lake")
    )
    parser.add_argument(
        "--automq-bootstrap-servers", default=kafka_bootstrap_servers_from_env()
    )
    parser.add_argument(
        "--topic-prefix", default=os.getenv("COMPUTE_BAZAAR_TOPIC_PREFIX", "gpu")
    )
    parser.add_argument("--run-id")
    parser.add_argument("--trace-id")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip AutoMQ and keep publishing in memory",
    )


def _parse_query_object(value: str | None) -> dict[str, Any] | None:
    if value is None:
        return None
    parsed = _parse_query(value)
    if parsed is None:
        return None
    if not isinstance(parsed, dict):
        raise SystemExit("--query must be a JSON object for this provider")
    return parsed


def _parse_csv(value: str | None) -> list[str] | None:
    if value is None:
        return None
    values = [part.strip() for part in value.split(",") if part.strip()]
    return values or None


def _read_sql_input(*, sql: str | None, sql_file: str | None) -> str:
    if bool(sql) == bool(sql_file):
        raise SystemExit("Provide exactly one of --sql or --sql-file")
    if sql_file:
        with open(sql_file, encoding="utf-8") as file:
            return file.read()
    assert sql is not None
    return sql


def _print_json(value: Any) -> None:
    print(json.dumps(to_jsonable(value), indent=2, sort_keys=True))


def _load_local_env(path: str = ".env") -> None:
    """Load simple KEY=VALUE lines from a local .env file without overriding shell env."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def _read_optional_secret_file(path: str) -> str | None:
    if not os.path.exists(path):
        return None
    value = open(path, encoding="utf-8").read().strip()
    return value or None


if __name__ == "__main__":
    main()
