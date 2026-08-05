"""Windmill script for the full hourly Compute Bazaar market run."""

# the_compute_bazaar is installed in the custom worker image and allowlisted locally.

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from the_compute_bazaar.prices.market_run import (
    default_market_providers,
    run_market_hourly,
)


def main(
    vast_api_key: str | None = None,
    lium_api_key: str | None = None,
    clore_api_key: str | None = None,
    prime_intellect_api_key: str | None = None,
    shadeform_api_key: str | None = None,
    sesterce_api_key: str | None = None,
    tensordock_api_key: str | None = None,
    hyperstack_api_key: str | None = None,
    lambda_cloud_api_key: str | None = None,
    digitalocean_api_token: str | None = None,
    gpus_io_api_key: str | None = None,
    getdeploying_api_key: str | None = None,
    jarvislabs_api_key: str | None = None,
    verda_client_id: str | None = None,
    verda_client_secret: str | None = None,
    raw_root: str | None = None,
    lake_root: str | None = None,
    dashboard_output_root: str = "data/dashboard/compute-bazaar",
    public_base_url: str | None = None,
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
    environment = {
        "VAST_API_KEY": vast_api_key,
        "LIUM_API_KEY": lium_api_key,
        "CLORE_API_KEY": clore_api_key,
        "PRIME_INTELLECT_API_KEY": prime_intellect_api_key,
        "SHADEFORM_API_KEY": shadeform_api_key,
        "SESTERCE_API_KEY": sesterce_api_key,
        "TENSORDOCK_API_KEY": tensordock_api_key,
        "HYPERSTACK_API_KEY": hyperstack_api_key,
        "LAMBDA_CLOUD_API_KEY": lambda_cloud_api_key,
        "DIGITALOCEAN_API_TOKEN": digitalocean_api_token,
        "GPUS_IO_API_KEY": gpus_io_api_key,
        "GETDEPLOYING_API_KEY": getdeploying_api_key,
        "JL_API_KEY": jarvislabs_api_key,
        "VERDA_CLIENT_ID": verda_client_id,
        "VERDA_CLIENT_SECRET": verda_client_secret,
        "COMPUTE_BAZAAR_PUBLIC_BASE_URL": public_base_url,
        "AWS_REGION": aws_region,
        "AWS_DEFAULT_REGION": aws_region,
    }
    kafka_config = {
        key: value
        for key, value in {
            "security.protocol": kafka_security_protocol,
            "sasl.mechanism": kafka_sasl_mechanism,
            "sasl.username": kafka_username,
            "sasl.password": kafka_password,
        }.items()
        if value
    }
    effective_raw_root = raw_root or os.getenv("COMPUTE_BAZAAR_RAW_ROOT", "data/raw")
    effective_lake_root = lake_root or os.getenv(
        "COMPUTE_BAZAAR_LAKE_ROOT", "data/lake"
    )
    provider_scope = (
        [item.strip() for item in providers.split(",") if item.strip()]
        if providers
        else None
    )

    with _temporary_environment(environment):
        result = run_market_hourly(
            raw_root=effective_raw_root,
            lake_root=effective_lake_root,
            dashboard_output_root=dashboard_output_root,
            providers=provider_scope or default_market_providers(),
            automq_bootstrap_servers=automq_bootstrap_servers,
            automq_config=kafka_config,
            topic_prefix=topic_prefix,
            run_id=run_id,
            dashboard_limit=dashboard_limit,
            lium_size=lium_size,
            lium_paginate=lium_paginate,
            lium_max_pages=lium_max_pages,
            dry_run=dry_run,
        )
    return result.to_dict()


@contextmanager
def _temporary_environment(values: dict[str, str | None]) -> Iterator[None]:
    previous = {key: os.environ.get(key) for key in values}
    try:
        for key, value in values.items():
            if value is not None:
                os.environ[key] = value
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
