"""Windmill script for the full hourly Compute Bazaar market run."""

from __future__ import annotations

import json
import os
import subprocess


DEFAULT_PROVIDER_SCOPE = (
    "vast,lium,spheron,inference_sh,clore,akash,aws_spot,azure,runpod,verda,"
    "published_rate_cards"
)


def main(
    vast_api_key: str | None = None,
    lium_api_key: str | None = None,
    prime_intellect_api_key: str | None = None,
    shadeform_api_key: str | None = None,
    sesterce_api_key: str | None = None,
    tensordock_api_key: str | None = None,
    hyperstack_api_key: str | None = None,
    lambda_cloud_api_key: str | None = None,
    digitalocean_api_token: str | None = None,
    gpus_io_api_key: str | None = None,
    verda_client_id: str | None = None,
    verda_client_secret: str | None = None,
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
    providers: str | None = None,
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
    _set_env_if_present(env, "PRIME_INTELLECT_API_KEY", prime_intellect_api_key)
    _set_env_if_present(env, "SHADEFORM_API_KEY", shadeform_api_key)
    _set_env_if_present(env, "SESTERCE_API_KEY", sesterce_api_key)
    _set_env_if_present(env, "TENSORDOCK_API_KEY", tensordock_api_key)
    _set_env_if_present(env, "HYPERSTACK_API_KEY", hyperstack_api_key)
    _set_env_if_present(env, "LAMBDA_CLOUD_API_KEY", lambda_cloud_api_key)
    _set_env_if_present(env, "DIGITALOCEAN_API_TOKEN", digitalocean_api_token)
    _set_env_if_present(env, "GPUS_IO_API_KEY", gpus_io_api_key)
    _set_env_if_present(env, "VERDA_CLIENT_ID", verda_client_id)
    _set_env_if_present(env, "VERDA_CLIENT_SECRET", verda_client_secret)
    _set_env_if_present(env, "COMPUTE_BAZAAR_RAW_ROOT", raw_root)
    _set_env_if_present(env, "COMPUTE_BAZAAR_LAKE_ROOT", lake_root)
    _set_env_if_present(
        env, "COMPUTE_BAZAAR_KAFKA_BOOTSTRAP_SERVERS", automq_bootstrap_servers
    )
    _set_env_if_present(
        env, "COMPUTE_BAZAAR_KAFKA_SECURITY_PROTOCOL", kafka_security_protocol
    )
    _set_env_if_present(
        env, "COMPUTE_BAZAAR_KAFKA_SASL_MECHANISM", kafka_sasl_mechanism
    )
    _set_env_if_present(env, "COMPUTE_BAZAAR_KAFKA_USERNAME", kafka_username)
    _set_env_if_present(env, "COMPUTE_BAZAAR_KAFKA_PASSWORD", kafka_password)
    _set_env_if_present(env, "AWS_REGION", aws_region)
    _set_env_if_present(env, "AWS_DEFAULT_REGION", aws_region)
    provider_scope = providers or _default_provider_scope(
        prime_intellect_api_key=prime_intellect_api_key,
        shadeform_api_key=shadeform_api_key,
        sesterce_api_key=sesterce_api_key,
        tensordock_api_key=tensordock_api_key,
        hyperstack_api_key=hyperstack_api_key,
        lambda_cloud_api_key=lambda_cloud_api_key,
        digitalocean_api_token=digitalocean_api_token,
        gpus_io_api_key=gpus_io_api_key,
    )

    command = [
        "/opt/compute-bazaar/.venv/bin/gpu-prices",
        "market-hourly",
        "--providers",
        provider_scope,
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

    completed = subprocess.run(
        command, check=True, capture_output=True, text=True, env=env
    )
    return json.loads(completed.stdout)


def _set_env_if_present(env: dict[str, str], name: str, value: str | None) -> None:
    if value is not None:
        env[name] = value


def _default_provider_scope(
    *,
    prime_intellect_api_key: str | None,
    shadeform_api_key: str | None,
    sesterce_api_key: str | None,
    tensordock_api_key: str | None,
    hyperstack_api_key: str | None,
    lambda_cloud_api_key: str | None,
    digitalocean_api_token: str | None,
    gpus_io_api_key: str | None,
) -> str:
    providers = DEFAULT_PROVIDER_SCOPE.split(",")
    for provider, key in (
        ("prime_intellect", prime_intellect_api_key),
        ("shadeform", shadeform_api_key),
        ("sesterce", sesterce_api_key),
        ("tensordock", tensordock_api_key),
        ("hyperstack", hyperstack_api_key),
        ("lambda", lambda_cloud_api_key),
        ("digitalocean", digitalocean_api_token),
        ("gpus_io", gpus_io_api_key),
    ):
        if key:
            providers.append(provider)
    return ",".join(providers)
