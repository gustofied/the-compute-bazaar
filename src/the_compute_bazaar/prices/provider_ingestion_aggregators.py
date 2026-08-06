"""Ingestion adapters for third-party GPU price aggregators."""

from __future__ import annotations

import os
import uuid

from .events import new_run_id
from .ingestion import IngestResult, persist_provider_snapshot
from .providers.cloud_gpu_prices import (
    CloudGpuPricesClient,
    normalize_external_offerings as normalize_cloud_gpu_prices_external_offerings,
)
from .providers.gpus_io import (
    GpusIoClient,
    normalize_prices as normalize_gpus_io_prices,
)
from .providers.getdeploying import (
    GetDeployingClient,
    normalize_external_offerings as normalize_getdeploying_external_offerings,
)
from .providers.gridstackhub import (
    GridStackHubClient,
    normalize_reference_prices as normalize_gridstackhub_reference_prices,
)
from .providers.shadeform import ShadeformClient, normalize_instance_types
from .schemas import utc_now
from .storage import date_partition


def ingest_gpus_io(
    *,
    api_key: str | None = None,
    raw_root: str = "data/raw",
    lake_root: str = "data/lake",
    automq_bootstrap_servers: str | None = None,
    automq_config: dict[str, str] | None = None,
    topic_prefix: str = "gpu",
    dry_run: bool = False,
    run_id: str | None = None,
    trace_id: str | None = None,
    api_base: str | None = None,
    max_pages: int = 20,
    page_size: int = 200,
) -> IngestResult:
    provider = "gpus_io"
    run_id = run_id or new_run_id(provider)
    trace_id = trace_id or uuid.uuid4().hex
    observed_at = utc_now()
    observed_date = observed_at.date().isoformat()
    raw_ref = date_partition(
        raw_root,
        provider=provider,
        observed_date=observed_date,
        run_id=run_id,
        filename="prices.json",
    )
    client = GpusIoClient(
        api_key=api_key or os.getenv("GPUS_IO_API_KEY", ""),
        **({"api_base": api_base} if api_base else {}),
    )
    fetched = client.fetch_prices(max_pages=max_pages, page_size=page_size)
    normalized, unknown_gpu_names = normalize_gpus_io_prices(
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
        unknown_gpu_names=unknown_gpu_names,
        snapshot_query={
            "source_type": "authenticated_live_multi_provider_price_feed",
            "max_pages": max_pages,
            "page_size": page_size,
        },
        automq_bootstrap_servers=automq_bootstrap_servers,
        automq_config=automq_config,
        topic_prefix=topic_prefix,
        dry_run=dry_run,
    )


def ingest_shadeform(
    *,
    api_key: str | None = None,
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
    provider = "shadeform"
    run_id = run_id or new_run_id(provider)
    trace_id = trace_id or uuid.uuid4().hex
    observed_at = utc_now()
    observed_date = observed_at.date().isoformat()
    raw_ref = date_partition(
        raw_root,
        provider=provider,
        observed_date=observed_date,
        run_id=run_id,
        filename="instance-types.json",
    )
    client = ShadeformClient(
        api_key=api_key or os.getenv("SHADEFORM_API_KEY", ""),
        **({"api_base": api_base} if api_base else {}),
    )
    fetched = client.fetch_instance_types()
    normalized, unknown_gpu_names = normalize_instance_types(
        fetched.instance_types,
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
        raw_offer_count=len(fetched.instance_types),
        normalized=normalized,
        unknown_gpu_names=unknown_gpu_names,
        snapshot_query={"source_type": "live_multi_cloud_inventory", "available": True},
        automq_bootstrap_servers=automq_bootstrap_servers,
        automq_config=automq_config,
        topic_prefix=topic_prefix,
        dry_run=dry_run,
    )


def ingest_gridstackhub(
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
    provider = "gridstackhub"
    run_id = run_id or new_run_id(provider)
    trace_id = trace_id or uuid.uuid4().hex
    observed_at = utc_now()
    raw_ref = date_partition(
        raw_root,
        provider=provider,
        observed_date=observed_at.date().isoformat(),
        run_id=run_id,
        filename="external-gpu-prices.json",
    )
    client = GridStackHubClient(
        **({"api_url": api_url} if api_url else {}),
    )
    fetched = client.fetch_prices()
    normalized, unknown_gpu_names = normalize_gridstackhub_reference_prices(
        fetched.rows,
        as_of=fetched.as_of,
        fetched_at=observed_at,
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
        raw_offer_count=len(fetched.rows),
        normalized=normalized,
        unknown_gpu_names=unknown_gpu_names,
        snapshot_query={
            "source_type": "external_gpu_price_reference",
            "benchmark_eligible": False,
        },
        automq_bootstrap_servers=automq_bootstrap_servers,
        automq_config=automq_config,
        topic_prefix=topic_prefix,
        dry_run=dry_run,
    )


def ingest_cloud_gpu_prices(
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
    page_size: int = 100,
    max_pages: int = 10,
) -> IngestResult:
    provider = "cloud_gpu_prices"
    run_id = run_id or new_run_id(provider)
    trace_id = trace_id or uuid.uuid4().hex
    observed_at = utc_now()
    raw_ref = date_partition(
        raw_root,
        provider=provider,
        observed_date=observed_at.date().isoformat(),
        run_id=run_id,
        filename="external-frontier-gpu-catalog.json",
    )
    client = CloudGpuPricesClient(
        **({"api_url": api_url} if api_url else {}),
    )
    fetched = client.fetch_frontier_offerings(
        page_size=page_size,
        max_pages=max_pages,
    )
    normalized, unknown_gpu_names = normalize_cloud_gpu_prices_external_offerings(
        fetched.offerings,
        generated_at=fetched.generated_at,
        fetched_at=observed_at,
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
        raw_offer_count=len(fetched.offerings),
        normalized=normalized,
        unknown_gpu_names=unknown_gpu_names,
        snapshot_query={
            "source_type": "public_external_gpu_catalog",
            "normalized_scope": "complete_comparable_frontier_gpu_prices",
            "benchmark_eligible": False,
        },
        automq_bootstrap_servers=automq_bootstrap_servers,
        automq_config=automq_config,
        topic_prefix=topic_prefix,
        dry_run=dry_run,
    )


def ingest_getdeploying(
    *,
    api_key: str | None = None,
    raw_root: str = "data/raw",
    lake_root: str = "data/lake",
    automq_bootstrap_servers: str | None = None,
    automq_config: dict[str, str] | None = None,
    topic_prefix: str = "gpu",
    dry_run: bool = False,
    run_id: str | None = None,
    trace_id: str | None = None,
    api_url: str | None = None,
    page_size: int = 100,
    max_pages: int = 20,
) -> IngestResult:
    provider = "getdeploying"
    api_key = api_key or os.getenv("GETDEPLOYING_API_KEY")
    if not api_key:
        raise ValueError(
            "GetDeploying API key is required. Set GETDEPLOYING_API_KEY or pass --api-key."
        )
    run_id = run_id or new_run_id(provider)
    trace_id = trace_id or uuid.uuid4().hex
    observed_at = utc_now()
    raw_ref = date_partition(
        raw_root,
        provider=provider,
        observed_date=observed_at.date().isoformat(),
        run_id=run_id,
        filename="external-frontier-gpu-offerings.json",
    )
    client = GetDeployingClient(
        api_key=api_key,
        **({"api_url": api_url} if api_url else {}),
    )
    fetched = client.fetch_frontier_offerings(
        page_size=page_size,
        max_pages=max_pages,
    )
    normalized, unknown_gpu_names = normalize_getdeploying_external_offerings(
        fetched.offerings,
        fetched_at=observed_at,
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
        raw_offer_count=len(fetched.offerings),
        normalized=normalized,
        unknown_gpu_names=unknown_gpu_names,
        snapshot_query={
            "source_type": "external_frontier_gpu_offerings",
            "benchmark_eligible": False,
        },
        automq_bootstrap_servers=automq_bootstrap_servers,
        automq_config=automq_config,
        topic_prefix=topic_prefix,
        dry_run=dry_run,
    )
