"""Windmill script for the full hourly Compute Bazaar market run."""

# the_compute_bazaar is installed in the custom worker image and allowlisted locally.

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager

from the_compute_bazaar.prices.market_run import (
    default_market_providers,
    run_market_hourly,
)
from the_compute_bazaar.prices.provider_registry import (
    provider_credentials as registered_provider_credentials,
)


def main(
    provider_credentials_json: str | None = None,
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
    required_providers: str | None = None,
    minimum_successful_providers: int = 1,
    dashboard_limit: int = 100,
    dry_run: bool = False,
    run_id: str | None = None,
) -> dict[str, object]:
    environment = {
        **_provider_credentials(provider_credentials_json),
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
    required_provider_scope = (
        [item.strip() for item in required_providers.split(",") if item.strip()]
        if required_providers
        else None
    )

    with _temporary_environment(environment):
        result = run_market_hourly(
            raw_root=effective_raw_root,
            lake_root=effective_lake_root,
            dashboard_output_root=dashboard_output_root,
            providers=provider_scope or default_market_providers(),
            required_providers=required_provider_scope,
            minimum_successful_providers=minimum_successful_providers,
            automq_bootstrap_servers=automq_bootstrap_servers,
            automq_config=kafka_config,
            topic_prefix=topic_prefix,
            run_id=run_id,
            dashboard_limit=dashboard_limit,
            dry_run=dry_run,
        )
    return result.to_dict()


def _provider_credentials(value: str | None) -> dict[str, str]:
    if not value:
        return {}
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("provider_credentials_json must contain a JSON object")
    allowed = {credential.env_name for credential in registered_provider_credentials()}
    unexpected = set(parsed) - allowed
    if unexpected:
        raise ValueError(
            "Unknown provider credential names: "
            + ", ".join(sorted(str(name) for name in unexpected))
        )
    return {
        str(name): str(secret)
        for name, secret in parsed.items()
        if name and secret is not None and str(secret)
    }


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
