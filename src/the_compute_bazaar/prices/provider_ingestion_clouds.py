"""Ingestion adapters for specialist GPU clouds."""

from __future__ import annotations

import os
import uuid

from .events import new_run_id
from .ingestion import IngestResult, persist_provider_snapshot
from .market_state_hyperstack import normalize_hyperstack_market_state
from .providers.hyperstack import HyperstackClient, normalize_stock
from .providers.inference_sh import (
    InferenceShClient,
    normalize_instance_types as normalize_inference_sh_instance_types,
)
from .providers.jarvislabs import (
    JarvisLabsClient,
    normalize_gpu_availability as normalize_jarvislabs_availability,
)
from .providers.lambda_cloud import (
    LambdaCloudClient,
    normalize_instance_types as normalize_lambda_instance_types,
)
from .providers.sesterce import (
    SesterceClient,
    normalize_offers as normalize_sesterce_offers,
)
from .providers.thunder_compute import ThunderComputeClient, normalize_catalog
from .providers.verda import VerdaClient, normalize_instance_catalog
from .schemas import utc_now
from .storage import date_partition


def ingest_inference_sh(
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
    provider = "inference_sh"
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
    client = InferenceShClient(
        **({"api_base": api_base} if api_base else {}),
    )
    fetched = client.fetch_instance_types()
    normalized, unknown_gpu_names = normalize_inference_sh_instance_types(
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
        snapshot_query={
            "source_type": "public_hourly_cached_cross_cloud_catalog",
            "upstream_catalog": "shadeform",
        },
        automq_bootstrap_servers=automq_bootstrap_servers,
        automq_config=automq_config,
        topic_prefix=topic_prefix,
        dry_run=dry_run,
    )


def ingest_sesterce(
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
    provider = "sesterce"
    run_id = run_id or new_run_id(provider)
    trace_id = trace_id or uuid.uuid4().hex
    observed_at = utc_now()
    observed_date = observed_at.date().isoformat()
    raw_ref = date_partition(
        raw_root,
        provider=provider,
        observed_date=observed_date,
        run_id=run_id,
        filename="offers.json",
    )
    client = SesterceClient(
        api_key=api_key or os.getenv("SESTERCE_API_KEY", ""),
        **({"api_base": api_base} if api_base else {}),
    )
    fetched = client.fetch_offers()
    normalized, unknown_gpu_names = normalize_sesterce_offers(
        fetched.offers,
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
        raw_offer_count=len(fetched.offers),
        normalized=normalized,
        unknown_gpu_names=unknown_gpu_names,
        snapshot_query={"source_type": "live_gpu_cloud_offers", "available": True},
        automq_bootstrap_servers=automq_bootstrap_servers,
        automq_config=automq_config,
        topic_prefix=topic_prefix,
        dry_run=dry_run,
    )


def ingest_verda(
    *,
    client_id: str | None = None,
    client_secret: str | None = None,
    access_token: str | None = None,
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
    provider = "verda"
    run_id = run_id or new_run_id(provider)
    trace_id = trace_id or uuid.uuid4().hex
    observed_at = utc_now()
    observed_date = observed_at.date().isoformat()
    raw_ref = date_partition(
        raw_root,
        provider=provider,
        observed_date=observed_date,
        run_id=run_id,
        filename="instance-catalog.json",
    )
    client = VerdaClient(
        client_id=client_id or os.getenv("VERDA_CLIENT_ID") or None,
        client_secret=client_secret or os.getenv("VERDA_CLIENT_SECRET") or None,
        access_token=access_token or os.getenv("VERDA_ACCESS_TOKEN") or None,
        **({"api_base": api_base} if api_base else {}),
    )
    fetched = client.fetch_catalog()
    normalized, unknown_gpu_names = normalize_instance_catalog(
        fetched.instance_types,
        availability=fetched.availability,
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
        snapshot_query={
            "source_type": (
                "direct_gpu_catalog_with_live_availability"
                if fetched.availability is not None
                else "direct_public_gpu_catalog"
            ),
            "availability_authenticated": fetched.availability is not None,
        },
        automq_bootstrap_servers=automq_bootstrap_servers,
        automq_config=automq_config,
        topic_prefix=topic_prefix,
        dry_run=dry_run,
    )


def ingest_hyperstack(
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
    provider = "hyperstack"
    run_id = run_id or new_run_id(provider)
    trace_id = trace_id or uuid.uuid4().hex
    observed_at = utc_now()
    observed_date = observed_at.date().isoformat()
    raw_ref = date_partition(
        raw_root,
        provider=provider,
        observed_date=observed_date,
        run_id=run_id,
        filename="stock-and-pricebook.json",
    )
    client = HyperstackClient(
        api_key=api_key or os.getenv("HYPERSTACK_API_KEY", ""),
        **({"api_base": api_base} if api_base else {}),
    )
    fetched = client.fetch_stock_and_prices()
    normalized, unknown_gpu_names = normalize_stock(
        fetched.stocks,
        pricebook=fetched.pricebook,
        observed_at=observed_at,
        raw_ref=raw_ref,
    )
    market_state = normalize_hyperstack_market_state(
        fetched.stocks,
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
        raw_offer_count=sum(
            len(stock.get("models") or [])
            for stock in fetched.stocks
            if isinstance(stock.get("models"), list)
        ),
        normalized=normalized,
        unknown_gpu_names=unknown_gpu_names,
        snapshot_query={
            "source_type": "real_time_stock_and_current_pricebook",
        },
        automq_bootstrap_servers=automq_bootstrap_servers,
        automq_config=automq_config,
        topic_prefix=topic_prefix,
        dry_run=dry_run,
        market_state=market_state,
    )


def ingest_lambda_cloud(
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
    provider = "lambda"
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
    client = LambdaCloudClient(
        api_key=api_key or os.getenv("LAMBDA_CLOUD_API_KEY", ""),
        **({"api_base": api_base} if api_base else {}),
    )
    fetched = client.fetch_instance_types()
    normalized, unknown_gpu_names = normalize_lambda_instance_types(
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
        snapshot_query={
            "source_type": "live_instance_types_and_capacity_regions",
        },
        automq_bootstrap_servers=automq_bootstrap_servers,
        automq_config=automq_config,
        topic_prefix=topic_prefix,
        dry_run=dry_run,
    )


def ingest_thunder_compute(
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
    provider = "thunder_compute"
    run_id = run_id or new_run_id(provider)
    trace_id = trace_id or uuid.uuid4().hex
    observed_at = utc_now()
    raw_ref = date_partition(
        raw_root,
        provider=provider,
        observed_date=observed_at.date().isoformat(),
        run_id=run_id,
        filename="catalog.json",
    )
    client = ThunderComputeClient(
        **({"api_base": api_base} if api_base else {}),
    )
    fetched = client.fetch_catalog()
    normalized, unknown_gpu_names = normalize_catalog(
        fetched.pricing,
        fetched.availability,
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
        raw_offer_count=len(fetched.availability.get("specs", {})),
        normalized=normalized,
        unknown_gpu_names=unknown_gpu_names,
        snapshot_query={
            "source_type": "public_live_gpu_pricing_and_availability",
        },
        automq_bootstrap_servers=automq_bootstrap_servers,
        automq_config=automq_config,
        topic_prefix=topic_prefix,
        dry_run=dry_run,
    )


def ingest_jarvislabs(
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
    provider = "jarvislabs"
    run_id = run_id or new_run_id(provider)
    trace_id = trace_id or uuid.uuid4().hex
    observed_at = utc_now()
    raw_ref = date_partition(
        raw_root,
        provider=provider,
        observed_date=observed_at.date().isoformat(),
        run_id=run_id,
        filename="availability.json",
    )
    client = JarvisLabsClient(
        api_key=api_key or os.getenv("JL_API_KEY", ""),
        **({"api_base": api_base} if api_base else {}),
    )
    fetched = client.fetch_gpu_availability()
    normalized, unknown_gpu_names = normalize_jarvislabs_availability(
        fetched.rows,
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
        raw_offer_count=len(fetched.rows),
        normalized=normalized,
        unknown_gpu_names=unknown_gpu_names,
        snapshot_query={
            "source_type": "authenticated_live_gpu_prices_and_free_devices",
        },
        automq_bootstrap_servers=automq_bootstrap_servers,
        automq_config=automq_config,
        topic_prefix=topic_prefix,
        dry_run=dry_run,
    )
