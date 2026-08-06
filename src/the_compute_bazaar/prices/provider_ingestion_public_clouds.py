"""Ingestion adapters for public-cloud GPU rate sources."""

from __future__ import annotations

import os
import uuid
from typing import Any

from .events import new_run_id
from .ingestion import IngestResult, persist_provider_snapshot
from .providers.aws_spot import AwsSpotClient, normalize_spot_prices
from .providers.azure_retail import AzureRetailClient, normalize_retail_prices
from .providers.digitalocean import (
    DigitalOceanClient,
    normalize_sizes as normalize_digitalocean_sizes,
)
from .providers.oracle_cloud import (
    OracleCloudClient,
    normalize_gpu_products as normalize_oracle_gpu_products,
)
from .providers.ovhcloud import (
    OvhCloudClient,
    normalize_gpu_plans as normalize_ovhcloud_gpu_plans,
)
from .providers.scaleway import ScalewayClient, normalize_gpu_products
from .providers.vultr import VultrClient, normalize_gpu_plans
from .schemas import utc_now
from .storage import date_partition


def ingest_aws_spot(
    *,
    raw_root: str = "data/raw",
    lake_root: str = "data/lake",
    automq_bootstrap_servers: str | None = None,
    automq_config: dict[str, str] | None = None,
    topic_prefix: str = "gpu",
    dry_run: bool = False,
    run_id: str | None = None,
    trace_id: str | None = None,
    regions: list[str] | None = None,
    session: Any | None = None,
) -> IngestResult:
    provider = "aws_spot"
    run_id = run_id or new_run_id(provider)
    trace_id = trace_id or uuid.uuid4().hex
    observed_at = utc_now()
    observed_date = observed_at.date().isoformat()
    raw_ref = date_partition(
        raw_root,
        provider=provider,
        observed_date=observed_date,
        run_id=run_id,
        filename="spot-prices.json",
    )

    client = AwsSpotClient(session=session, regions=regions)
    fetched = client.fetch_current_prices(observed_at=observed_at)
    normalized, unknown_instance_types = normalize_spot_prices(
        fetched.prices,
        observed_at=observed_at,
        raw_ref=raw_ref,
    )
    return persist_provider_snapshot(
        provider=provider,
        run_id=run_id,
        trace_id=trace_id,
        observed_at=observed_at,
        lake_root=lake_root,
        raw_ref=raw_ref,
        raw_payload=fetched.raw_payload,
        raw_offer_count=len(fetched.prices),
        normalized=normalized,
        unknown_gpu_names=unknown_instance_types,
        snapshot_query={
            "source_type": "aws_ec2_spot_price_history",
            "regions": list(client.regions),
            "price_basis": "spot_instance_hour",
            "capacity_confirmed": False,
        },
        automq_bootstrap_servers=automq_bootstrap_servers,
        automq_config=automq_config,
        topic_prefix=topic_prefix,
        dry_run=dry_run,
    )


def ingest_azure_retail(
    *,
    raw_root: str = "data/raw",
    lake_root: str = "data/lake",
    automq_bootstrap_servers: str | None = None,
    automq_config: dict[str, str] | None = None,
    topic_prefix: str = "gpu",
    dry_run: bool = False,
    run_id: str | None = None,
    trace_id: str | None = None,
    prices_url: str | None = None,
    max_pages_per_sku: int = 10,
) -> IngestResult:
    provider = "azure"
    run_id = run_id or new_run_id(provider)
    trace_id = trace_id or uuid.uuid4().hex
    observed_at = utc_now()
    observed_date = observed_at.date().isoformat()
    raw_ref = date_partition(
        raw_root,
        provider=provider,
        observed_date=observed_date,
        run_id=run_id,
        filename="retail-prices.json",
    )

    client = AzureRetailClient(
        **({"prices_url": prices_url} if prices_url else {}),
    )
    fetched = client.fetch_frontier_prices(max_pages_per_sku=max_pages_per_sku)
    normalized, unknown_skus = normalize_retail_prices(
        fetched.prices,
        observed_at=observed_at,
        raw_ref=raw_ref,
    )
    return persist_provider_snapshot(
        provider=provider,
        run_id=run_id,
        trace_id=trace_id,
        observed_at=observed_at,
        lake_root=lake_root,
        raw_ref=raw_ref,
        raw_payload=fetched.raw_payload,
        raw_offer_count=len(fetched.prices),
        normalized=normalized,
        unknown_gpu_names=unknown_skus,
        snapshot_query={
            "source_type": "public_retail_prices_api",
            "rate_scope": "frontier_gpu_virtual_machines",
            "capacity_confirmed": False,
        },
        automq_bootstrap_servers=automq_bootstrap_servers,
        automq_config=automq_config,
        topic_prefix=topic_prefix,
        dry_run=dry_run,
    )


def ingest_digitalocean(
    *,
    api_token: str | None = None,
    raw_root: str = "data/raw",
    lake_root: str = "data/lake",
    automq_bootstrap_servers: str | None = None,
    automq_config: dict[str, str] | None = None,
    topic_prefix: str = "gpu",
    dry_run: bool = False,
    run_id: str | None = None,
    trace_id: str | None = None,
    api_base: str | None = None,
    max_pages: int = 10,
) -> IngestResult:
    provider = "digitalocean"
    run_id = run_id or new_run_id(provider)
    trace_id = trace_id or uuid.uuid4().hex
    observed_at = utc_now()
    observed_date = observed_at.date().isoformat()
    raw_ref = date_partition(
        raw_root,
        provider=provider,
        observed_date=observed_date,
        run_id=run_id,
        filename="sizes.json",
    )
    client = DigitalOceanClient(
        api_token=api_token or os.getenv("DIGITALOCEAN_API_TOKEN", ""),
        **({"api_base": api_base} if api_base else {}),
    )
    fetched = client.fetch_sizes(max_pages=max_pages)
    normalized, unknown_gpu_names = normalize_digitalocean_sizes(
        fetched.sizes,
        observed_at=observed_at,
        raw_ref=raw_ref,
    )
    return persist_provider_snapshot(
        provider=provider,
        run_id=run_id,
        trace_id=trace_id,
        observed_at=observed_at,
        lake_root=lake_root,
        raw_ref=raw_ref,
        raw_payload=fetched.raw_payload,
        raw_offer_count=len(fetched.sizes),
        normalized=normalized,
        unknown_gpu_names=unknown_gpu_names,
        snapshot_query={
            "source_type": "live_gpu_droplet_sizes_and_regions",
            "max_pages": max_pages,
        },
        automq_bootstrap_servers=automq_bootstrap_servers,
        automq_config=automq_config,
        topic_prefix=topic_prefix,
        dry_run=dry_run,
    )


def ingest_vultr(
    *,
    raw_root: str = "data/raw",
    lake_root: str = "data/lake",
    automq_bootstrap_servers: str | None = None,
    automq_config: dict[str, str] | None = None,
    topic_prefix: str = "gpu",
    dry_run: bool = False,
    run_id: str | None = None,
    trace_id: str | None = None,
    api_base: str | None = None,
) -> IngestResult:
    provider = "vultr"
    run_id = run_id or new_run_id(provider)
    trace_id = trace_id or uuid.uuid4().hex
    observed_at = utc_now()
    raw_ref = date_partition(
        raw_root,
        provider=provider,
        observed_date=observed_at.date().isoformat(),
        run_id=run_id,
        filename="gpu-plans.json",
    )
    client = VultrClient(
        **({"api_base": api_base} if api_base else {}),
    )
    fetched = client.fetch_gpu_catalog()
    normalized, unknown_gpu_names = normalize_gpu_plans(
        fetched.plans,
        available_regions_by_plan=fetched.available_regions_by_plan,
        observed_at=observed_at,
        raw_ref=raw_ref,
    )
    return persist_provider_snapshot(
        provider=provider,
        run_id=run_id,
        trace_id=trace_id,
        observed_at=observed_at,
        lake_root=lake_root,
        raw_ref=raw_ref,
        raw_payload=fetched.raw_payload,
        raw_offer_count=len(fetched.plans),
        normalized=normalized,
        unknown_gpu_names=unknown_gpu_names,
        snapshot_query={
            "source_type": "public_gpu_plans_and_regional_deployability",
        },
        automq_bootstrap_servers=automq_bootstrap_servers,
        automq_config=automq_config,
        topic_prefix=topic_prefix,
        dry_run=dry_run,
    )


def ingest_scaleway(
    *,
    raw_root: str = "data/raw",
    lake_root: str = "data/lake",
    automq_bootstrap_servers: str | None = None,
    automq_config: dict[str, str] | None = None,
    topic_prefix: str = "gpu",
    dry_run: bool = False,
    run_id: str | None = None,
    trace_id: str | None = None,
    api_base: str | None = None,
    fx_url: str | None = None,
) -> IngestResult:
    provider = "scaleway"
    run_id = run_id or new_run_id(provider)
    trace_id = trace_id or uuid.uuid4().hex
    observed_at = utc_now()
    raw_ref = date_partition(
        raw_root,
        provider=provider,
        observed_date=observed_at.date().isoformat(),
        run_id=run_id,
        filename="gpu-products.json",
    )
    client = ScalewayClient(
        **({"api_base": api_base} if api_base else {}),
        **({"fx_url": fx_url} if fx_url else {}),
    )
    fetched = client.fetch_gpu_catalog()
    normalized, unknown_gpu_names = normalize_gpu_products(
        fetched.products,
        eur_usd_rate=fetched.eur_usd_rate,
        fx_observed_date=fetched.fx_observed_date,
        observed_at=observed_at,
        raw_ref=raw_ref,
    )
    return persist_provider_snapshot(
        provider=provider,
        run_id=run_id,
        trace_id=trace_id,
        observed_at=observed_at,
        lake_root=lake_root,
        raw_ref=raw_ref,
        raw_payload=fetched.raw_payload,
        raw_offer_count=len(fetched.products),
        normalized=normalized,
        unknown_gpu_names=unknown_gpu_names,
        snapshot_query={
            "source_type": "public_zone_gpu_prices_and_availability",
            "fx_source": "ecb_reference_rate",
        },
        automq_bootstrap_servers=automq_bootstrap_servers,
        automq_config=automq_config,
        topic_prefix=topic_prefix,
        dry_run=dry_run,
    )


def ingest_oracle_cloud(
    *,
    raw_root: str = "data/raw",
    lake_root: str = "data/lake",
    automq_bootstrap_servers: str | None = None,
    automq_config: dict[str, str] | None = None,
    topic_prefix: str = "gpu",
    dry_run: bool = False,
    run_id: str | None = None,
    trace_id: str | None = None,
    api_url: str | None = None,
) -> IngestResult:
    provider = "oracle_cloud"
    run_id = run_id or new_run_id(provider)
    trace_id = trace_id or uuid.uuid4().hex
    observed_at = utc_now()
    raw_ref = date_partition(
        raw_root,
        provider=provider,
        observed_date=observed_at.date().isoformat(),
        run_id=run_id,
        filename="gpu-list-prices.json",
    )
    client = OracleCloudClient(
        **({"api_url": api_url} if api_url else {}),
    )
    fetched = client.fetch_gpu_catalog()
    normalized, unknown_gpu_names = normalize_oracle_gpu_products(
        fetched.products,
        observed_at=observed_at,
        raw_ref=raw_ref,
    )
    return persist_provider_snapshot(
        provider=provider,
        run_id=run_id,
        trace_id=trace_id,
        observed_at=observed_at,
        lake_root=lake_root,
        raw_ref=raw_ref,
        raw_payload=fetched.raw_payload,
        raw_offer_count=len(fetched.products),
        normalized=normalized,
        unknown_gpu_names=unknown_gpu_names,
        snapshot_query={
            "source_type": "public_gpu_list_price_api",
            "availability_claim": "none",
        },
        automq_bootstrap_servers=automq_bootstrap_servers,
        automq_config=automq_config,
        topic_prefix=topic_prefix,
        dry_run=dry_run,
    )


def ingest_ovhcloud(
    *,
    raw_root: str = "data/raw",
    lake_root: str = "data/lake",
    automq_bootstrap_servers: str | None = None,
    automq_config: dict[str, str] | None = None,
    topic_prefix: str = "gpu",
    dry_run: bool = False,
    run_id: str | None = None,
    trace_id: str | None = None,
    catalog_url: str | None = None,
    fx_url: str | None = None,
) -> IngestResult:
    provider = "ovhcloud"
    run_id = run_id or new_run_id(provider)
    trace_id = trace_id or uuid.uuid4().hex
    observed_at = utc_now()
    raw_ref = date_partition(
        raw_root,
        provider=provider,
        observed_date=observed_at.date().isoformat(),
        run_id=run_id,
        filename="gpu-instance-catalog.json",
    )
    client = OvhCloudClient(
        **({"catalog_url": catalog_url} if catalog_url else {}),
        **({"fx_url": fx_url} if fx_url else {}),
    )
    fetched = client.fetch_gpu_catalog()
    normalized, unknown_gpu_names = normalize_ovhcloud_gpu_plans(
        fetched.plans,
        eur_usd_rate=fetched.eur_usd_rate,
        fx_observed_date=fetched.fx_observed_date,
        observed_at=observed_at,
        raw_ref=raw_ref,
    )
    return persist_provider_snapshot(
        provider=provider,
        run_id=run_id,
        trace_id=trace_id,
        observed_at=observed_at,
        lake_root=lake_root,
        raw_ref=raw_ref,
        raw_payload=fetched.raw_payload,
        raw_offer_count=len(fetched.plans),
        normalized=normalized,
        unknown_gpu_names=unknown_gpu_names,
        snapshot_query={
            "source_type": "public_gpu_instance_catalog",
            "fx_source": "ecb_reference_rate",
            "availability_claim": "none",
        },
        automq_bootstrap_servers=automq_bootstrap_servers,
        automq_config=automq_config,
        topic_prefix=topic_prefix,
        dry_run=dry_run,
    )
