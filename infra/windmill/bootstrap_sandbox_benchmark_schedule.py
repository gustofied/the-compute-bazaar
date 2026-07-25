"""Bootstrap the disabled-by-default daily sandbox benchmark job."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError

from bootstrap_provider_schedule import (
    DEFAULT_BASE_URL,
    DEFAULT_FOLDER,
    DEFAULT_WORKSPACE,
    WindmillClient,
    _load_local_env,
    _read_token_file,
)
from sandbox_benchmark_daily import DEFAULT_PROVIDERS


DEFAULT_CRON = "0 30 6 * * *"


def main() -> None:
    _load_local_env()
    parser = argparse.ArgumentParser(
        description="Create or update the daily sandbox benchmark job"
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
        default=os.getenv("WINDMILL_TOKEN") or _read_token_file(),
    )
    parser.add_argument(
        "--timezone",
        default=os.getenv("WINDMILL_TIMEZONE", "UTC"),
    )
    parser.add_argument(
        "--cron",
        default=os.getenv("WINDMILL_SANDBOX_BENCHMARK_CRON", DEFAULT_CRON),
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
        "--dispatch",
        action="store_true",
        help="Dispatch the credentialed benchmark after ingesting prior results",
    )
    parser.add_argument(
        "--enable",
        action="store_true",
        help="Enable the recurring schedule; it is disabled by default",
    )
    parser.add_argument("--run-now", action="store_true")
    parser.add_argument("--wait", action="store_true")
    parser.add_argument("--providers", default=DEFAULT_PROVIDERS)
    parser.add_argument("--suites", default="realworld")
    parser.add_argument("--replicas", default="12")
    parser.add_argument("--pts-passes", default="")
    args = parser.parse_args()

    if not args.token:
        raise SystemExit(
            "Set WINDMILL_TOKEN, pass --token, or create "
            ".secrets/windmill-bootstrap-token.txt"
        )
    variables = required_variables(
        args.folder,
        source_repository=args.source_repository,
        dispatch=args.dispatch,
    )
    client = WindmillClient(
        base_url=args.base_url,
        workspace=args.workspace,
        token=args.token,
    )
    client.create_folder(args.folder)
    for variable in variables:
        client.upsert_variable(**variable)

    script_path = f"f/{args.folder}/sandbox_benchmark_daily"
    schedule_path = f"f/{args.folder}/sandbox_benchmark_daily_schedule"
    script_body = (
        Path(__file__)
        .with_name("sandbox_benchmark_daily.py")
        .read_text(encoding="utf-8")
    )
    client.upsert_script(
        path=script_path,
        content=script_body,
        summary="Daily controlled sandbox benchmark",
        description=(
            "Ingests the latest trusted StarSling dataset into immutable "
            "bronze and normalized silver, then optionally dispatches the "
            "next credentialed realworld benchmark."
        ),
    )
    run_args = schedule_args(
        args.folder,
        source_ref=args.source_ref,
        dispatch=args.dispatch,
        providers=args.providers,
        suites=args.suites,
        replicas=args.replicas,
        pts_passes=args.pts_passes,
    )
    client.upsert_schedule(
        path=schedule_path,
        script_path=script_path,
        schedule=args.cron,
        timezone=args.timezone,
        enabled=args.enable,
        summary="Daily controlled sandbox benchmark",
        description=(
            "Retains validated workload history; dispatch requires an owned "
            "benchmark repository and GitHub environment secrets."
        ),
        args=run_args,
    )

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
                "enabled": args.enable,
                "dispatch": args.dispatch,
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
    dispatch: bool,
) -> list[dict[str, Any]]:
    lake_root = os.getenv("COMPUTE_BAZAAR_LAKE_ROOT")
    if not lake_root:
        raise SystemExit("Missing required environment variable: COMPUTE_BAZAAR_LAKE_ROOT")
    variables = [
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
    ]
    if not dispatch:
        return variables

    dispatch_repository = os.getenv("SANDBOX_BENCHMARK_DISPATCH_REPOSITORY")
    github_token = os.getenv("SANDBOX_BENCHMARK_GITHUB_TOKEN")
    missing = [
        name
        for name, value in (
            ("SANDBOX_BENCHMARK_DISPATCH_REPOSITORY", dispatch_repository),
            ("SANDBOX_BENCHMARK_GITHUB_TOKEN", github_token),
        )
        if not value
    ]
    if missing:
        raise SystemExit(
            "Missing required dispatch variables: " + ", ".join(missing)
        )
    variables.extend(
        [
            {
                "path": f"f/{folder}/sandbox_benchmark_dispatch_repository",
                "value": dispatch_repository,
                "is_secret": False,
                "description": "Owned benchmark repository to dispatch",
            },
            {
                "path": f"f/{folder}/sandbox_benchmark_github_token",
                "value": github_token,
                "is_secret": True,
                "description": "Fine-grained token for benchmark workflow dispatch",
            },
        ]
    )
    return variables


def schedule_args(
    folder: str,
    *,
    source_ref: str,
    dispatch: bool,
    providers: str,
    suites: str,
    replicas: str,
    pts_passes: str,
) -> dict[str, Any]:
    args: dict[str, Any] = {
        "source_repository": (
            f"$var:f/{folder}/sandbox_benchmark_source_repository"
        ),
        "source_ref": source_ref,
        "lake_root": f"$var:f/{folder}/lake_root",
        "dispatch": dispatch,
        "providers": providers,
        "suites": suites,
        "replicas": replicas,
        "pts_passes": pts_passes,
    }
    if dispatch:
        args.update(
            {
                "dispatch_repository": (
                    f"$var:f/{folder}/sandbox_benchmark_dispatch_repository"
                ),
                "github_token": (
                    f"$var:f/{folder}/sandbox_benchmark_github_token"
                ),
            }
        )
    return args


if __name__ == "__main__":
    try:
        main()
    except HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        print(f"Windmill API error {error.code}: {body}", file=sys.stderr)
        raise SystemExit(1) from error
