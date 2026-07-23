"""Bootstrap the complete Windmill market heartbeat job."""

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
    DEFAULT_CRON,
    DEFAULT_FOLDER,
    DEFAULT_WORKSPACE,
    WindmillClient,
    _load_local_env,
    _read_token_file,
)


DEFAULT_PROVIDER_SCOPE = "vast,lium,crusoe,hyperstack,lambda,nebius,runpod,tensordock"


def main() -> None:
    _load_local_env()

    parser = argparse.ArgumentParser(description="Create or update the Windmill market heartbeat job")
    parser.add_argument("--base-url", default=os.getenv("WINDMILL_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--workspace", default=os.getenv("WINDMILL_WORKSPACE", DEFAULT_WORKSPACE))
    parser.add_argument("--folder", default=os.getenv("WINDMILL_FOLDER", DEFAULT_FOLDER))
    parser.add_argument("--token", default=os.getenv("WINDMILL_TOKEN") or _read_token_file())
    parser.add_argument("--timezone", default=os.getenv("WINDMILL_TIMEZONE", "UTC"))
    parser.add_argument("--cron", default=os.getenv("WINDMILL_MARKET_CRON", DEFAULT_CRON))
    parser.add_argument("--disabled", action="store_true", help="Create the schedule disabled")
    parser.add_argument("--run-now", action="store_true", help="Run the market script once after upsert")
    parser.add_argument("--run-id", help="Optional market_run_id to pass to the one-off run")
    parser.add_argument("--wait", action="store_true", help="Wait for the one-off run and include its result")
    parser.add_argument("--dashboard-limit", type=int, default=100)
    parser.add_argument("--lium-size", type=int, default=200)
    parser.add_argument("--lium-max-pages", type=int, default=10)
    parser.add_argument("--no-lium-pagination", action="store_true")
    args = parser.parse_args()

    if not args.token:
        raise SystemExit("Set WINDMILL_TOKEN, pass --token, or create .secrets/windmill-bootstrap-token.txt")

    client = WindmillClient(base_url=args.base_url, workspace=args.workspace, token=args.token)
    folder = args.folder

    client.create_folder(folder)
    for variable in required_variables(folder):
        client.upsert_variable(**variable)

    script_path = f"f/{folder}/market_hourly"
    schedule_path = f"f/{folder}/market_hourly_hourly"
    script_body = Path(__file__).with_name("market_hourly.py").read_text(encoding="utf-8")

    client.upsert_script(
        path=script_path,
        content=script_body,
        summary="Hourly Compute Bazaar market heartbeat",
        description=(
            "Ingests Vast, Lium, and official published rate cards, builds gold, "
            "exports dashboard JSON, and writes a market run manifest."
        ),
    )
    run_args = schedule_args(
        folder,
        dashboard_limit=args.dashboard_limit,
        lium_size=args.lium_size,
        lium_max_pages=args.lium_max_pages,
        lium_paginate=not args.no_lium_pagination,
    )
    client.upsert_schedule(
        path=schedule_path,
        script_path=script_path,
        schedule=args.cron,
        timezone=args.timezone,
        enabled=not args.disabled,
        summary="Hourly Compute Bazaar market heartbeat",
        description="Runs the full provider-to-dashboard market refresh.",
        args=run_args,
    )

    job_id = None
    job_result = None
    if args.run_now:
        one_off_args = dict(run_args)
        if args.run_id:
            one_off_args["run_id"] = args.run_id
        if args.wait:
            job_result = client.run_script_wait_result(script_path, one_off_args)
        else:
            job_id = client.run_script(script_path, one_off_args)

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


def required_variables(folder: str) -> list[dict[str, Any]]:
    env_to_variable = [
        ("VAST_API_KEY", "vast_api_key", True, "Vast API key"),
        ("LIUM_API_KEY", "lium_api_key", True, "Lium API key"),
        ("COMPUTE_BAZAAR_RAW_ROOT", "raw_root", False, "Raw S3 root"),
        ("COMPUTE_BAZAAR_LAKE_ROOT", "lake_root", False, "Lake S3 root"),
        ("COMPUTE_BAZAAR_KAFKA_BOOTSTRAP_SERVERS", "kafka_bootstrap_servers", False, "Kafka bootstrap servers"),
        ("COMPUTE_BAZAAR_KAFKA_USERNAME", "kafka_username", True, "Kafka SASL username"),
        ("COMPUTE_BAZAAR_KAFKA_PASSWORD", "kafka_password", True, "Kafka SASL password"),
    ]
    variables: list[dict[str, Any]] = []
    missing: list[str] = []
    for env_name, variable_name, is_secret, description in env_to_variable:
        value = os.getenv(env_name)
        if value is None:
            missing.append(env_name)
            continue
        variables.append(
            {
                "path": f"f/{folder}/{variable_name}",
                "value": value,
                "is_secret": is_secret,
                "description": description,
            }
        )
    if missing:
        raise SystemExit(f"Missing required environment variables: {', '.join(missing)}")

    variables.append(
        {
            "path": f"f/{folder}/dashboard_output_root",
            "value": _dashboard_output_root(),
            "is_secret": False,
            "description": "Public-safe dashboard JSON output root",
        }
    )
    return variables


def schedule_args(
    folder: str,
    *,
    dashboard_limit: int,
    lium_size: int,
    lium_max_pages: int,
    lium_paginate: bool,
) -> dict[str, Any]:
    return {
        "vast_api_key": f"$var:f/{folder}/vast_api_key",
        "lium_api_key": f"$var:f/{folder}/lium_api_key",
        "raw_root": f"$var:f/{folder}/raw_root",
        "lake_root": f"$var:f/{folder}/lake_root",
        "dashboard_output_root": f"$var:f/{folder}/dashboard_output_root",
        "automq_bootstrap_servers": f"$var:f/{folder}/kafka_bootstrap_servers",
        "kafka_security_protocol": "SASL_PLAINTEXT",
        "kafka_sasl_mechanism": "SCRAM-SHA-256",
        "kafka_username": f"$var:f/{folder}/kafka_username",
        "kafka_password": f"$var:f/{folder}/kafka_password",
        "aws_region": os.getenv("AWS_REGION", "eu-west-3"),
        "topic_prefix": "gpu",
        "providers": DEFAULT_PROVIDER_SCOPE,
        "lium_size": lium_size,
        "lium_max_pages": lium_max_pages,
        "lium_paginate": lium_paginate,
        "dashboard_limit": dashboard_limit,
        "dry_run": False,
    }


def _dashboard_output_root() -> str:
    configured = os.getenv("COMPUTE_BAZAAR_DASHBOARD_OUTPUT_ROOT")
    if configured:
        return configured

    lake_root = os.getenv("COMPUTE_BAZAAR_LAKE_ROOT", "").rstrip("/")
    if lake_root.startswith("s3://") and lake_root.endswith("/lake"):
        return f"{lake_root[:-5]}/dashboard/compute-bazaar"
    return "data/dashboard/compute-bazaar"


if __name__ == "__main__":
    try:
        main()
    except HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        print(f"Windmill API error {error.code}: {body}", file=sys.stderr)
        raise SystemExit(1) from error
