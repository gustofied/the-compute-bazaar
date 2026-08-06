"""Ingestion adapters for live GPU marketplaces."""

from __future__ import annotations

import os
import uuid
from typing import Any

from .events import new_run_id
from .ingestion import IngestResult, persist_provider_snapshot
from .market_state_akash import normalize_akash_market_state
from .market_state_clore import normalize_clore_market_state
from .market_state_prime import normalize_prime_market_state
from .market_state_runpod import normalize_runpod_market_state
from .providers.akash import AkashClient, normalize_gpu_prices
from .providers.clore import CloreClient, normalize_servers
from .providers.lium import LiumClient, normalize_executors
from .providers.prime_intellect import PrimeIntellectClient, normalize_availability
from .providers.runpod import RunpodClient, normalize_gpu_types
from .providers.spheron import (
    SpheronClient,
    normalize_offers as normalize_spheron_offers,
)
from .providers.tensordock import TensorDockClient, normalize_hostnodes
from .providers.vast import VastClient, extract_offers, normalize_offers
from .schemas import utc_now
from .storage import date_partition


def ingest_vast(
    *,
    api_key: str | None = None,
    query: str | dict[str, Any] | None = None,
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
    provider = "vast"
    run_id = run_id or new_run_id(provider)
    trace_id = trace_id or uuid.uuid4().hex
    observed_at = utc_now()
    observed_date = observed_at.date().isoformat()

    client = VastClient(
        api_key=api_key or os.getenv("VAST_API_KEY"),
        **({"api_base": api_base} if api_base else {}),
    )
    if query is None:
        fetched = client.fetch_market_segments()
        payload = fetched.raw_payload
        offers = fetched.offers
        effective_query: str | dict[str, Any] = {
            "mode": "segmented_market_search",
            "segments": [
                {
                    "segment": segment.get("segment"),
                    "query": segment.get("query"),
                }
                for segment in payload["segments"]
            ],
        }
    else:
        effective_query = query
        payload = client.search_bundles(query=effective_query)
        offers = extract_offers(payload)
    raw_ref = date_partition(
        raw_root,
        provider=provider,
        observed_date=observed_date,
        run_id=run_id,
        filename="bundles.json",
    )
    normalized, unknown_gpu_names = normalize_offers(
        offers, observed_at=observed_at, raw_ref=raw_ref
    )
    return persist_provider_snapshot(
        provider=provider,
        run_id=run_id,
        trace_id=trace_id,
        observed_at=observed_at,
        lake_root=lake_root,
        raw_ref=raw_ref,
        raw_payload=payload,
        raw_offer_count=len(offers),
        normalized=normalized,
        unknown_gpu_names=unknown_gpu_names,
        snapshot_query=(
            effective_query
            if isinstance(effective_query, dict)
            else {"q": effective_query}
        ),
        automq_bootstrap_servers=automq_bootstrap_servers,
        automq_config=automq_config,
        topic_prefix=topic_prefix,
        dry_run=dry_run,
    )


def ingest_lium(
    *,
    api_key: str | None = None,
    query: dict[str, Any] | None = None,
    raw_root: str = "data/raw",
    lake_root: str = "data/lake",
    automq_bootstrap_servers: str | None = None,
    automq_config: dict[str, str] | None = None,
    topic_prefix: str = "gpu",
    dry_run: bool = False,
    run_id: str | None = None,
    trace_id: str | None = None,
    api_base: str | None = None,
    paginate: bool = False,
    max_pages: int = 10,
) -> IngestResult:
    provider = "lium"
    run_id = run_id or new_run_id(provider)
    trace_id = trace_id or uuid.uuid4().hex
    observed_at = utc_now()
    observed_date = observed_at.date().isoformat()

    client = LiumClient(
        api_key=api_key or os.getenv("LIUM_API_KEY"),
        **({"api_base": api_base} if api_base else {}),
    )
    fetched = client.fetch_executor_pages(
        query=query, paginate=paginate, max_pages=max_pages
    )
    executors = fetched.executors
    raw_ref = date_partition(
        raw_root,
        provider=provider,
        observed_date=observed_date,
        run_id=run_id,
        filename="executors.json",
    )
    normalized, unknown_gpu_names = normalize_executors(
        executors, observed_at=observed_at, raw_ref=raw_ref
    )
    return persist_provider_snapshot(
        provider=provider,
        run_id=run_id,
        trace_id=trace_id,
        observed_at=observed_at,
        lake_root=lake_root,
        raw_ref=raw_ref,
        raw_payload=fetched.raw_payload,
        raw_offer_count=len(executors),
        normalized=normalized,
        unknown_gpu_names=unknown_gpu_names,
        snapshot_query={
            **(query or {}),
            "paginate": paginate,
            "max_pages": max_pages if paginate else None,
        },
        automq_bootstrap_servers=automq_bootstrap_servers,
        automq_config=automq_config,
        topic_prefix=topic_prefix,
        dry_run=dry_run,
    )


def ingest_akash(
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
    providers_url: str | None = None,
) -> IngestResult:
    provider = "akash"
    run_id = run_id or new_run_id(provider)
    trace_id = trace_id or uuid.uuid4().hex
    observed_at = utc_now()
    observed_date = observed_at.date().isoformat()
    raw_ref = date_partition(
        raw_root,
        provider=provider,
        observed_date=observed_date,
        run_id=run_id,
        filename="gpu-prices.json",
    )
    client = AkashClient(
        **({"prices_url": prices_url} if prices_url else {}),
        **({"providers_url": providers_url} if providers_url else {}),
    )
    fetched = client.fetch_gpu_prices()
    normalized, unknown_gpu_names = normalize_gpu_prices(
        fetched.models,
        observed_at=observed_at,
        raw_ref=raw_ref,
    )
    market_state = normalize_akash_market_state(
        models=fetched.models,
        providers=fetched.providers,
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
        raw_offer_count=len(fetched.models),
        normalized=normalized,
        unknown_gpu_names=unknown_gpu_names,
        snapshot_query={"source_type": "live_gpu_price_and_availability_summary"},
        automq_bootstrap_servers=automq_bootstrap_servers,
        automq_config=automq_config,
        topic_prefix=topic_prefix,
        dry_run=dry_run,
        market_state=market_state,
    )


def ingest_prime_intellect(
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
    max_pages_per_gpu: int = 20,
) -> IngestResult:
    provider = "prime_intellect"
    run_id = run_id or new_run_id(provider)
    trace_id = trace_id or uuid.uuid4().hex
    observed_at = utc_now()
    observed_date = observed_at.date().isoformat()
    raw_ref = date_partition(
        raw_root,
        provider=provider,
        observed_date=observed_date,
        run_id=run_id,
        filename="availability.json",
    )
    client = PrimeIntellectClient(
        api_key=api_key or os.getenv("PRIME_INTELLECT_API_KEY", ""),
        **({"api_base": api_base} if api_base else {}),
    )
    fetched = client.fetch_frontier_availability(max_pages_per_gpu=max_pages_per_gpu)
    normalized, unknown_gpu_names = normalize_availability(
        fetched.items,
        observed_at=observed_at,
        raw_ref=raw_ref,
    )
    market_state = normalize_prime_market_state(
        fetched.items,
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
        raw_offer_count=len(fetched.items),
        normalized=normalized,
        unknown_gpu_names=unknown_gpu_names,
        snapshot_query={
            "source_type": "live_gpu_availability",
            "gpu_types": fetched.raw_payload["gpu_types"],
            "max_pages_per_gpu": max_pages_per_gpu,
        },
        automq_bootstrap_servers=automq_bootstrap_servers,
        automq_config=automq_config,
        topic_prefix=topic_prefix,
        dry_run=dry_run,
        market_state=market_state,
    )


def ingest_spheron(
    *,
    raw_root: str = "data/raw",
    lake_root: str = "data/lake",
    automq_bootstrap_servers: str | None = None,
    automq_config: dict[str, str] | None = None,
    topic_prefix: str = "gpu",
    dry_run: bool = False,
    run_id: str | None = None,
    trace_id: str | None = None,
    offers_url: str | None = None,
) -> IngestResult:
    provider = "spheron"
    run_id = run_id or new_run_id(provider)
    trace_id = trace_id or uuid.uuid4().hex
    observed_at = utc_now()
    observed_date = observed_at.date().isoformat()
    raw_ref = date_partition(
        raw_root,
        provider=provider,
        observed_date=observed_date,
        run_id=run_id,
        filename="gpu-offers.json",
    )
    client = SpheronClient(**({"offers_url": offers_url} if offers_url else {}))
    fetched = client.fetch_offers()
    normalized, unknown_gpu_names = normalize_spheron_offers(
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
        snapshot_query={"source_type": "live_multi_provider_gpu_offers"},
        automq_bootstrap_servers=automq_bootstrap_servers,
        automq_config=automq_config,
        topic_prefix=topic_prefix,
        dry_run=dry_run,
    )


def ingest_runpod(
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
    graphql_url: str | None = None,
) -> IngestResult:
    provider = "runpod"
    run_id = run_id or new_run_id(provider)
    trace_id = trace_id or uuid.uuid4().hex
    observed_at = utc_now()
    observed_date = observed_at.date().isoformat()
    raw_ref = date_partition(
        raw_root,
        provider=provider,
        observed_date=observed_date,
        run_id=run_id,
        filename="gpu-types.json",
    )
    client = RunpodClient(
        api_key=api_key or os.getenv("RUNPOD_API_KEY") or None,
        **({"graphql_url": graphql_url} if graphql_url else {}),
    )
    fetched = client.fetch_gpu_types()
    normalized, unknown_gpu_names = normalize_gpu_types(
        fetched.gpu_types,
        observed_at=observed_at,
        raw_ref=raw_ref,
    )
    market_state = normalize_runpod_market_state(
        fetched.gpu_types,
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
        raw_offer_count=len(fetched.gpu_types),
        normalized=normalized,
        unknown_gpu_names=unknown_gpu_names,
        snapshot_query={"source_type": "live_gpu_type_pricing", "gpu_count": 1},
        automq_bootstrap_servers=automq_bootstrap_servers,
        automq_config=automq_config,
        topic_prefix=topic_prefix,
        dry_run=dry_run,
        market_state=market_state,
    )


def ingest_clore(
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
    marketplace_url: str | None = None,
) -> IngestResult:
    provider = "clore"
    run_id = run_id or new_run_id(provider)
    trace_id = trace_id or uuid.uuid4().hex
    observed_at = utc_now()
    observed_date = observed_at.date().isoformat()
    raw_ref = date_partition(
        raw_root,
        provider=provider,
        observed_date=observed_date,
        run_id=run_id,
        filename="marketplace.json",
    )
    client = CloreClient(
        api_key=api_key or os.getenv("CLORE_API_KEY", ""),
        **({"marketplace_url": marketplace_url} if marketplace_url else {}),
    )
    fetched = client.fetch_marketplace()
    normalized, unknown_gpu_names = normalize_servers(
        fetched.servers,
        observed_at=observed_at,
        raw_ref=raw_ref,
    )
    market_state = normalize_clore_market_state(
        fetched.servers,
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
        raw_offer_count=len(fetched.servers),
        normalized=normalized,
        unknown_gpu_names=unknown_gpu_names,
        snapshot_query={
            "source_type": "authenticated_live_gpu_marketplace",
            "available_only": True,
        },
        automq_bootstrap_servers=automq_bootstrap_servers,
        automq_config=automq_config,
        topic_prefix=topic_prefix,
        dry_run=dry_run,
        market_state=market_state,
    )


def ingest_tensordock(
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
    provider = "tensordock"
    run_id = run_id or new_run_id(provider)
    trace_id = trace_id or uuid.uuid4().hex
    observed_at = utc_now()
    observed_date = observed_at.date().isoformat()
    raw_ref = date_partition(
        raw_root,
        provider=provider,
        observed_date=observed_date,
        run_id=run_id,
        filename="hostnodes.json",
    )
    client = TensorDockClient(
        api_key=api_key or os.getenv("TENSORDOCK_API_KEY", ""),
        **({"api_base": api_base} if api_base else {}),
    )
    fetched = client.fetch_hostnodes()
    normalized, unknown_gpu_names = normalize_hostnodes(
        fetched.hostnodes,
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
        raw_offer_count=len(fetched.hostnodes),
        normalized=normalized,
        unknown_gpu_names=unknown_gpu_names,
        snapshot_query={
            "source_type": "live_hostnode_stock",
            "price_basis": "gpu_component_hour",
            "benchmark_eligible": False,
        },
        automq_bootstrap_servers=automq_bootstrap_servers,
        automq_config=automq_config,
        topic_prefix=topic_prefix,
        dry_run=dry_run,
    )
