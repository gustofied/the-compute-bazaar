"""Bootstrap the weekly public StarSling source poll."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError

from client import (
    DEFAULT_BASE_URL,
    DEFAULT_FOLDER,
    DEFAULT_WORKSPACE,
    WindmillClient,
    load_local_env,
    read_token_file,
)
DEFAULT_CRON = "0 30 6 * * 1"


def main() -> None:
    load_local_env()
    parser = argparse.ArgumentParser(
        description="Create or update the weekly StarSling source poll"
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("WINDMILL_BASE_URL", DEFAULT_BASE_URL),
    )
    parser.add_argument(
        "--workspace",
        default=os.getenv("WINDMILL_WORKSPACE", DEFAULT_WORKSPACE),
    )
    parser.add_argument(
        "--folder",
        default=os.getenv("WINDMILL_FOLDER", DEFAULT_FOLDER),
    )
    parser.add_argument(
        "--token",
        default=os.getenv("WINDMILL_TOKEN") or read_token_file(),
    )
    parser.add_argument(
        "--timezone",
        default=os.getenv("WINDMILL_TIMEZONE", "UTC"),
    )
    parser.add_argument(
        "--cron",
        default=os.getenv("WINDMILL_STARSLING_CRON", DEFAULT_CRON),
    )
    parser.add_argument(
        "--source-repository",
        default=os.getenv(
            "SANDBOX_BENCHMARK_SOURCE_REPOSITORY",
            "starslingdev/hpc-sandbox-benchmarks",
        ),
    )
    parser.add_argument(
        "--source-ref",
        default=os.getenv("SANDBOX_BENCHMARK_SOURCE_REF", "main"),
    )
    parser.add_argument(
        "--aws-region",
        default=os.getenv("AWS_REGION", "eu-west-3"),
    )
    parser.add_argument(
        "--disabled",
        action="store_true",
        help="Create the recurring source poll disabled",
    )
    parser.add_argument("--run-now", action="store_true")
    parser.add_argument("--wait", action="store_true")
    args = parser.parse_args()

    if not args.token:
        raise SystemExit(
            "Set WINDMILL_TOKEN, pass --token, or create "
            ".secrets/windmill-bootstrap-token.txt"
        )
    variables = required_variables(
        args.folder,
        source_repository=args.source_repository,
    )
    client = WindmillClient(
        base_url=args.base_url,
        workspace=args.workspace,
        token=args.token,
    )
    client.create_folder(args.folder)
    for variable in variables:
        client.upsert_variable(**variable)

    script_path = f"f/{args.folder}/sandbox_benchmark_weekly"
    schedule_path = f"f/{args.folder}/sandbox_benchmark_weekly_schedule"
    script_body = (
        Path(__file__)
        .with_name("sandbox_benchmark_weekly.py")
        .read_text(encoding="utf-8")
    )
    client.upsert_script(
        path=script_path,
        content=script_body,
        summary="Weekly public StarSling source poll",
        description=(
            "Ingests the latest trusted StarSling dataset into immutable "
            "bronze and content-addressed silver. It does not execute paid "
            "sandbox workloads."
        ),
    )
    run_args = schedule_args(
        args.folder,
        source_ref=args.source_ref,
        aws_region=args.aws_region,
    )
    client.upsert_schedule(
        path=schedule_path,
        script_path=script_path,
        schedule=args.cron,
        timezone=args.timezone,
        enabled=not args.disabled,
        summary="Weekly public StarSling source poll",
        description=(
            "Polls public committed benchmark results and retains only new "
            "compatible source generations."
        ),
        args=run_args,
    )
    client.delete_schedule(f"f/{args.folder}/sandbox_benchmark_daily_schedule")
    client.delete_script(f"f/{args.folder}/sandbox_benchmark_daily")

    job_id = None
    job_result = None
    if args.run_now:
        if args.wait:
            job_result = client.run_script_wait_result(script_path, run_args)
        else:
            job_id = client.run_script(script_path, run_args)
    print(
        json.dumps(
            {
                "workspace": args.workspace,
                "script_path": script_path,
                "schedule_path": schedule_path,
                "schedule": args.cron,
                "enabled": not args.disabled,
                "job_id": job_id,
                "job_result": job_result,
            },
            indent=2,
            sort_keys=True,
        )
    )


def required_variables(
    folder: str,
    *,
    source_repository: str,
) -> list[dict[str, Any]]:
    lake_root = os.getenv("COMPUTE_BAZAAR_LAKE_ROOT")
    dashboard_output_root = os.getenv("COMPUTE_BAZAAR_DASHBOARD_OUTPUT_ROOT")
    if not lake_root:
        raise SystemExit("Missing required environment variable: COMPUTE_BAZAAR_LAKE_ROOT")
    if not dashboard_output_root:
        raise SystemExit(
            "Missing required environment variable: "
            "COMPUTE_BAZAAR_DASHBOARD_OUTPUT_ROOT"
        )
    return [
        {
            "path": f"f/{folder}/sandbox_benchmark_source_repository",
            "value": source_repository,
            "is_secret": False,
            "description": "Trusted StarSling dataset owner/repository",
        },
        {
            "path": f"f/{folder}/lake_root",
            "value": lake_root,
            "is_secret": False,
            "description": "Compute Bazaar lake S3 root",
        },
        {
            "path": f"f/{folder}/dashboard_output_root",
            "value": dashboard_output_root,
            "is_secret": False,
            "description": "Public-safe dashboard JSON output root",
        },
    ]


def schedule_args(
    folder: str,
    *,
    source_ref: str,
    aws_region: str,
) -> dict[str, Any]:
    return {
        "source_repository": (
            f"$var:f/{folder}/sandbox_benchmark_source_repository"
        ),
        "source_ref": source_ref,
        "lake_root": f"$var:f/{folder}/lake_root",
        "dashboard_output_root": f"$var:f/{folder}/dashboard_output_root",
        "aws_region": aws_region,
    }


if __name__ == "__main__":
    try:
        main()
    except HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        print(f"Windmill API error {error.code}: {body}", file=sys.stderr)
        raise SystemExit(1) from error
