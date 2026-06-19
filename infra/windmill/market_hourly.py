"""Windmill script for the full hourly Compute Bazaar market run."""

from __future__ import annotations

import json
import os
import subprocess


def main(
    vast_api_key: str | None = None,
    lium_api_key: str | None = None,
    raw_root: str | None = None,
    lake_root: str | None = None,
    dashboard_output_root: str = "data/dashboard/compute-bazaar",
    automq_bootstrap_servers: str | None = None,
    kafka_security_protocol: str | None = None,
    kafka_sasl_mechanism: str | None = None,
    kafka_username: str | None = None,
    kafka_password: str | None = None,
    aws_region: str = "eu-west-3",
    topic_prefix: str = "gpu",
    providers: str = "vast,lium",
    lium_size: int = 200,
    lium_max_pages: int = 10,
    lium_paginate: bool = True,
    dashboard_limit: int = 100,
    dry_run: bool = False,
    run_id: str | None = None,
) -> dict[str, object]:
    env = os.environ.copy()
    _set_env_if_present(env, "VAST_API_KEY", vast_api_key)
    _set_env_if_present(env, "LIUM_API_KEY", lium_api_key)
    _set_env_if_present(env, "COMPUTE_BAZAAR_RAW_ROOT", raw_root)
    _set_env_if_present(env, "COMPUTE_BAZAAR_LAKE_ROOT", lake_root)
    _set_env_if_present(env, "COMPUTE_BAZAAR_KAFKA_BOOTSTRAP_SERVERS", automq_bootstrap_servers)
    _set_env_if_present(env, "COMPUTE_BAZAAR_KAFKA_SECURITY_PROTOCOL", kafka_security_protocol)
    _set_env_if_present(env, "COMPUTE_BAZAAR_KAFKA_SASL_MECHANISM", kafka_sasl_mechanism)
    _set_env_if_present(env, "COMPUTE_BAZAAR_KAFKA_USERNAME", kafka_username)
    _set_env_if_present(env, "COMPUTE_BAZAAR_KAFKA_PASSWORD", kafka_password)
    _set_env_if_present(env, "AWS_REGION", aws_region)
    _set_env_if_present(env, "AWS_DEFAULT_REGION", aws_region)

    command = [
        "/opt/compute-bazaar/.venv/bin/gpu-prices",
        "market-hourly",
        "--providers",
        providers,
        "--dashboard-output-root",
        dashboard_output_root,
        "--lium-size",
        str(lium_size),
        "--lium-max-pages",
        str(lium_max_pages),
        "--dashboard-limit",
        str(dashboard_limit),
        "--topic-prefix",
        topic_prefix,
    ]
    if raw_root:
        command.extend(["--raw-root", raw_root])
    if lake_root:
        command.extend(["--lake-root", lake_root])
    if automq_bootstrap_servers:
        command.extend(["--automq-bootstrap-servers", automq_bootstrap_servers])
    if run_id:
        command.extend(["--run-id", run_id])
    if not lium_paginate:
        command.append("--no-lium-pagination")
    if dry_run:
        command.append("--dry-run")

    completed = subprocess.run(command, check=True, capture_output=True, text=True, env=env)
    return json.loads(completed.stdout)


def _set_env_if_present(env: dict[str, str], name: str, value: str | None) -> None:
    if value is not None:
        env[name] = value
