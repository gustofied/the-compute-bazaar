"""Windmill script for hourly Lium GPU price ingestion."""

from __future__ import annotations

import json
import os
import subprocess
from typing import Any


def main(
    api_key: str | None = None,
    query: dict[str, Any] | None = None,
    page: int | None = None,
    size: int = 200,
    raw_root: str | None = None,
    lake_root: str | None = None,
    automq_bootstrap_servers: str | None = None,
    kafka_security_protocol: str | None = None,
    kafka_sasl_mechanism: str | None = None,
    kafka_username: str | None = None,
    kafka_password: str | None = None,
    aws_region: str = "eu-west-3",
    topic_prefix: str = "gpu",
    dry_run: bool = False,
    run_id: str | None = None,
    trace_id: str | None = None,
    api_base: str | None = None,
) -> dict[str, Any]:
    env = os.environ.copy()
    _set_env_if_present(env, "LIUM_API_KEY", api_key)
    _set_env_if_present(env, "COMPUTE_BAZAAR_RAW_ROOT", raw_root)
    _set_env_if_present(env, "COMPUTE_BAZAAR_LAKE_ROOT", lake_root)
    _set_env_if_present(env, "COMPUTE_BAZAAR_KAFKA_BOOTSTRAP_SERVERS", automq_bootstrap_servers)
    _set_env_if_present(env, "COMPUTE_BAZAAR_KAFKA_SECURITY_PROTOCOL", kafka_security_protocol)
    _set_env_if_present(env, "COMPUTE_BAZAAR_KAFKA_SASL_MECHANISM", kafka_sasl_mechanism)
    _set_env_if_present(env, "COMPUTE_BAZAAR_KAFKA_USERNAME", kafka_username)
    _set_env_if_present(env, "COMPUTE_BAZAAR_KAFKA_PASSWORD", kafka_password)
    _set_env_if_present(env, "AWS_REGION", aws_region)
    _set_env_if_present(env, "AWS_DEFAULT_REGION", aws_region)

    command = ["/opt/compute-bazaar/.venv/bin/gpu-prices", "ingest-lium"]
    if query is not None:
        command.extend(["--query", json.dumps(query)])
    if page is not None:
        command.extend(["--page", str(page)])
    if size is not None:
        command.extend(["--size", str(size)])
    if topic_prefix:
        command.extend(["--topic-prefix", topic_prefix])
    if run_id:
        command.extend(["--run-id", run_id])
    if trace_id:
        command.extend(["--trace-id", trace_id])
    if api_base:
        command.extend(["--api-base", api_base])
    if dry_run:
        command.append("--dry-run")

    completed = subprocess.run(command, check=True, capture_output=True, text=True, env=env)
    return json.loads(completed.stdout)


def _set_env_if_present(env: dict[str, str], name: str, value: str | None) -> None:
    if value is not None:
        env[name] = value
