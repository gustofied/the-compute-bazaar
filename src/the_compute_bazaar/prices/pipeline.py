"""End-to-end provider ingestion pipelines."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .automq import DryRunPublisher, KafkaPublisher, Publisher, kafka_config_from_env
from .events import make_event, new_run_id, sha256_json
from .manifest import write_run_manifest
from .providers.akash import AkashClient, normalize_gpu_prices
from .providers.aws_spot import AwsSpotClient, normalize_spot_prices
from .providers.azure_retail import AzureRetailClient, normalize_retail_prices
from .providers.clore import CloreClient, normalize_servers
from .providers.digitalocean import (
    DigitalOceanClient,
    normalize_sizes as normalize_digitalocean_sizes,
)
from .providers.gpus_io import (
    GpusIoClient,
    normalize_prices as normalize_gpus_io_prices,
)
from .providers.hyperstack import HyperstackClient, normalize_stock
from .providers.inference_sh import (
    InferenceShClient,
    normalize_instance_types as normalize_inference_sh_instance_types,
)
from .providers.lambda_cloud import (
    LambdaCloudClient,
    normalize_instance_types as normalize_lambda_instance_types,
)
from .providers.lium import LiumClient, normalize_executors
from .providers.prime_intellect import PrimeIntellectClient, normalize_availability
from .providers.rate_cards import (
    DEFAULT_RATE_CARD_PROVIDER,
    normalize_rate_card_entries,
    rate_card_entries,
    rate_card_raw_payload,
)
from .providers.runpod import RunpodClient, normalize_gpu_types
from .providers.sesterce import (
    SesterceClient,
    normalize_offers as normalize_sesterce_offers,
)
from .providers.shadeform import ShadeformClient, normalize_instance_types
from .providers.spheron import (
    SpheronClient,
    normalize_offers as normalize_spheron_offers,
)
from .providers.tensordock import TensorDockClient, normalize_hostnodes
from .providers.verda import VerdaClient, normalize_instance_catalog
from .providers.vast import VastClient, extract_offers, normalize_offers
from .schemas import GpuOffer, ProviderSnapshot, utc_now
from .storage import date_partition, table_partition, write_json, write_offers_parquet


@dataclass(frozen=True)
class IngestResult:
    provider: str
    run_id: str
    raw_ref: str
    normalized_ref: str | None
    raw_offer_count: int
    normalized_offer_count: int
    unknown_gpu_names: list[str]
    published_events: int
    publish_mode: str
    manifest_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "run_id": self.run_id,
            "raw_ref": self.raw_ref,
            "normalized_ref": self.normalized_ref,
            "raw_offer_count": self.raw_offer_count,
            "normalized_offer_count": self.normalized_offer_count,
            "unknown_gpu_names": self.unknown_gpu_names,
            "published_events": self.published_events,
            "publish_mode": self.publish_mode,
            "manifest_ref": self.manifest_ref,
        }


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
    raw_payload_hash = sha256_json(payload)

    raw_ref = date_partition(
        raw_root,
        provider=provider,
        observed_date=observed_date,
        run_id=run_id,
        filename="bundles.json",
    )
    write_json(raw_ref, payload)

    normalized, unknown_gpu_names = normalize_offers(
        offers, observed_at=observed_at, raw_ref=raw_ref
    )
    normalized_ref: str | None = None
    if normalized:
        normalized_ref = table_partition(
            lake_root,
            table="silver/gpu_offers",
            observed_date=observed_date,
            provider=provider,
            run_id=run_id,
            filename="offers.parquet",
        )
        write_offers_parquet(normalized_ref, normalized)

    publisher = _publisher(
        automq_bootstrap_servers=automq_bootstrap_servers,
        automq_config=automq_config,
        dry_run=dry_run,
    )

    published_events = 0
    snapshot = ProviderSnapshot(
        provider=provider,
        fetched_at=observed_at,
        raw_ref=raw_ref,
        payload_hash=raw_payload_hash,
        offer_count=len(offers),
        query=effective_query
        if isinstance(effective_query, dict)
        else {"q": effective_query},
    )
    snapshot_event = make_event(
        event_type="gpu.provider_snapshot.v1",
        provider=provider,
        payload=snapshot.to_dict(),
        run_id=run_id,
        trace_id=trace_id,
        raw_ref=raw_ref,
        event_time=observed_at,
    )
    publisher.publish(
        f"{topic_prefix}.provider_snapshot.v1", snapshot_event, key=provider
    )
    published_events += 1

    for offer in normalized:
        event = make_event(
            event_type="gpu.normalized_offer.v1",
            provider=provider,
            payload=offer.to_dict(),
            run_id=run_id,
            trace_id=trace_id,
            raw_ref=raw_ref,
            event_time=offer.observed_at,
        )
        publisher.publish(
            f"{topic_prefix}.normalized_offer.v1", event, key=offer.event_key()
        )
        published_events += 1

    publisher.flush()
    manifest = write_run_manifest(
        lake_root,
        provider=provider,
        run_id=run_id,
        observed_date=observed_date,
        raw_ref=raw_ref,
        normalized_ref=normalized_ref,
        raw_offer_count=len(offers),
        normalized_offer_count=len(normalized),
        published_events=published_events,
        unknown_gpu_names=unknown_gpu_names,
        publish_mode="dry_run" if dry_run or not automq_bootstrap_servers else "kafka",
    )

    return IngestResult(
        provider=provider,
        run_id=run_id,
        raw_ref=raw_ref,
        normalized_ref=normalized_ref,
        raw_offer_count=len(offers),
        normalized_offer_count=len(normalized),
        unknown_gpu_names=unknown_gpu_names,
        published_events=published_events,
        publish_mode="dry_run" if dry_run or not automq_bootstrap_servers else "kafka",
        manifest_ref=manifest.manifest_ref,
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
    raw_payload_hash = sha256_json(fetched.raw_payload)

    raw_ref = date_partition(
        raw_root,
        provider=provider,
        observed_date=observed_date,
        run_id=run_id,
        filename="executors.json",
    )
    write_json(raw_ref, fetched.raw_payload)

    normalized, unknown_gpu_names = normalize_executors(
        executors, observed_at=observed_at, raw_ref=raw_ref
    )
    normalized_ref: str | None = None
    if normalized:
        normalized_ref = table_partition(
            lake_root,
            table="silver/gpu_offers",
            observed_date=observed_date,
            provider=provider,
            run_id=run_id,
            filename="offers.parquet",
        )
        write_offers_parquet(normalized_ref, normalized)

    publisher = _publisher(
        automq_bootstrap_servers=automq_bootstrap_servers,
        automq_config=automq_config,
        dry_run=dry_run,
    )

    published_events = 0
    snapshot = ProviderSnapshot(
        provider=provider,
        fetched_at=observed_at,
        raw_ref=raw_ref,
        payload_hash=raw_payload_hash,
        offer_count=len(executors),
        query={
            **(query or {}),
            "paginate": paginate,
            "max_pages": max_pages if paginate else None,
        },
    )
    snapshot_event = make_event(
        event_type="gpu.provider_snapshot.v1",
        provider=provider,
        payload=snapshot.to_dict(),
        run_id=run_id,
        trace_id=trace_id,
        raw_ref=raw_ref,
        event_time=observed_at,
    )
    publisher.publish(
        f"{topic_prefix}.provider_snapshot.v1", snapshot_event, key=provider
    )
    published_events += 1

    for offer in normalized:
        event = make_event(
            event_type="gpu.normalized_offer.v1",
            provider=provider,
            payload=offer.to_dict(),
            run_id=run_id,
            trace_id=trace_id,
            raw_ref=raw_ref,
            event_time=offer.observed_at,
        )
        publisher.publish(
            f"{topic_prefix}.normalized_offer.v1", event, key=offer.event_key()
        )
        published_events += 1

    publisher.flush()
    manifest = write_run_manifest(
        lake_root,
        provider=provider,
        run_id=run_id,
        observed_date=observed_date,
        raw_ref=raw_ref,
        normalized_ref=normalized_ref,
        raw_offer_count=len(executors),
        normalized_offer_count=len(normalized),
        published_events=published_events,
        unknown_gpu_names=unknown_gpu_names,
        publish_mode="dry_run" if dry_run or not automq_bootstrap_servers else "kafka",
    )

    return IngestResult(
        provider=provider,
        run_id=run_id,
        raw_ref=raw_ref,
        normalized_ref=normalized_ref,
        raw_offer_count=len(executors),
        normalized_offer_count=len(normalized),
        unknown_gpu_names=unknown_gpu_names,
        published_events=published_events,
        publish_mode="dry_run" if dry_run or not automq_bootstrap_servers else "kafka",
        manifest_ref=manifest.manifest_ref,
    )


def ingest_rate_card(
    *,
    provider: str = DEFAULT_RATE_CARD_PROVIDER,
    raw_root: str = "data/raw",
    lake_root: str = "data/lake",
    automq_bootstrap_servers: str | None = None,
    automq_config: dict[str, str] | None = None,
    topic_prefix: str = "gpu",
    dry_run: bool = False,
    run_id: str | None = None,
    trace_id: str | None = None,
) -> IngestResult:
    """Ingest official published provider rate cards as benchmark observations."""
    provider_name = provider
    run_id = run_id or new_run_id(provider_name)
    trace_id = trace_id or uuid.uuid4().hex
    observed_at = utc_now()
    observed_date = observed_at.date().isoformat()
    payload = rate_card_raw_payload(provider_name)
    entries = rate_card_entries(provider_name)
    raw_payload_hash = sha256_json(payload)

    raw_ref = date_partition(
        raw_root,
        provider=provider_name,
        observed_date=observed_date,
        run_id=run_id,
        filename="rate-card.json",
    )
    write_json(raw_ref, payload)

    normalized, unknown_gpu_names = normalize_rate_card_entries(
        entries, observed_at=observed_at, raw_ref=raw_ref
    )
    normalized_ref: str | None = None
    if normalized:
        normalized_ref = table_partition(
            lake_root,
            table="silver/gpu_offers",
            observed_date=observed_date,
            provider=provider_name,
            run_id=run_id,
            filename="offers.parquet",
        )
        write_offers_parquet(normalized_ref, normalized)

    publisher = _publisher(
        automq_bootstrap_servers=automq_bootstrap_servers,
        automq_config=automq_config,
        dry_run=dry_run,
    )

    published_events = 0
    snapshot = ProviderSnapshot(
        provider=provider_name,
        fetched_at=observed_at,
        raw_ref=raw_ref,
        payload_hash=raw_payload_hash,
        offer_count=len(entries),
        query={"source_type": "published_rate_card", "provider": provider_name},
    )
    snapshot_event = make_event(
        event_type="gpu.provider_snapshot.v1",
        provider=provider_name,
        payload=snapshot.to_dict(),
        run_id=run_id,
        trace_id=trace_id,
        raw_ref=raw_ref,
        event_time=observed_at,
    )
    publisher.publish(
        f"{topic_prefix}.provider_snapshot.v1", snapshot_event, key=provider_name
    )
    published_events += 1

    for offer in normalized:
        event = make_event(
            event_type="gpu.normalized_offer.v1",
            provider=provider_name,
            payload=offer.to_dict(),
            run_id=run_id,
            trace_id=trace_id,
            raw_ref=raw_ref,
            event_time=offer.observed_at,
        )
        publisher.publish(
            f"{topic_prefix}.normalized_offer.v1", event, key=offer.event_key()
        )
        published_events += 1

    publisher.flush()
    manifest = write_run_manifest(
        lake_root,
        provider=provider_name,
        run_id=run_id,
        observed_date=observed_date,
        raw_ref=raw_ref,
        normalized_ref=normalized_ref,
        raw_offer_count=len(entries),
        normalized_offer_count=len(normalized),
        published_events=published_events,
        unknown_gpu_names=unknown_gpu_names,
        publish_mode="dry_run" if dry_run or not automq_bootstrap_servers else "kafka",
    )

    return IngestResult(
        provider=provider_name,
        run_id=run_id,
        raw_ref=raw_ref,
        normalized_ref=normalized_ref,
        raw_offer_count=len(entries),
        normalized_offer_count=len(normalized),
        unknown_gpu_names=unknown_gpu_names,
        published_events=published_events,
        publish_mode="dry_run" if dry_run or not automq_bootstrap_servers else "kafka",
        manifest_ref=manifest.manifest_ref,
    )


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
    return _persist_publish_snapshot(
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
    return _persist_publish_snapshot(
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
    client = AkashClient(**({"prices_url": prices_url} if prices_url else {}))
    fetched = client.fetch_gpu_prices()
    normalized, unknown_gpu_names = normalize_gpu_prices(
        fetched.models,
        observed_at=observed_at,
        raw_ref=raw_ref,
    )
    return _persist_publish_snapshot(
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
    return _persist_publish_snapshot(
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
    return _persist_publish_snapshot(
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
    return _persist_publish_snapshot(
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
    return _persist_publish_snapshot(
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
    return _persist_publish_snapshot(
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
    return _persist_publish_snapshot(
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
    return _persist_publish_snapshot(
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
    )


def ingest_clore(
    *,
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
        **({"marketplace_url": marketplace_url} if marketplace_url else {}),
    )
    fetched = client.fetch_marketplace()
    normalized, unknown_gpu_names = normalize_servers(
        fetched.servers,
        observed_at=observed_at,
        raw_ref=raw_ref,
    )
    return _persist_publish_snapshot(
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
            "source_type": "public_live_gpu_marketplace",
            "available_only": True,
        },
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
    return _persist_publish_snapshot(
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
    return _persist_publish_snapshot(
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
    return _persist_publish_snapshot(
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
    return _persist_publish_snapshot(
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
    return _persist_publish_snapshot(
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


def _persist_publish_snapshot(
    *,
    provider: str,
    run_id: str,
    trace_id: str,
    observed_at: datetime,
    lake_root: str,
    raw_ref: str,
    raw_payload: Any,
    raw_offer_count: int,
    normalized: list[GpuOffer],
    unknown_gpu_names: list[str],
    snapshot_query: dict[str, Any],
    automq_bootstrap_servers: str | None,
    automq_config: dict[str, str] | None,
    topic_prefix: str,
    dry_run: bool,
) -> IngestResult:
    observed_date = observed_at.date().isoformat()
    write_json(raw_ref, raw_payload)
    normalized_ref: str | None = None
    if normalized:
        normalized_ref = table_partition(
            lake_root,
            table="silver/gpu_offers",
            observed_date=observed_date,
            provider=provider,
            run_id=run_id,
            filename="offers.parquet",
        )
        write_offers_parquet(normalized_ref, normalized)

    publisher = _publisher(
        automq_bootstrap_servers=automq_bootstrap_servers,
        automq_config=automq_config,
        dry_run=dry_run,
    )
    snapshot = ProviderSnapshot(
        provider=provider,
        fetched_at=observed_at,
        raw_ref=raw_ref,
        payload_hash=sha256_json(raw_payload),
        offer_count=raw_offer_count,
        query=snapshot_query,
    )
    publisher.publish(
        f"{topic_prefix}.provider_snapshot.v1",
        make_event(
            event_type="gpu.provider_snapshot.v1",
            provider=provider,
            payload=snapshot.to_dict(),
            run_id=run_id,
            trace_id=trace_id,
            raw_ref=raw_ref,
            event_time=observed_at,
        ),
        key=provider,
    )
    published_events = 1
    for offer in normalized:
        publisher.publish(
            f"{topic_prefix}.normalized_offer.v1",
            make_event(
                event_type="gpu.normalized_offer.v1",
                provider=provider,
                payload=offer.to_dict(),
                run_id=run_id,
                trace_id=trace_id,
                raw_ref=raw_ref,
                event_time=offer.observed_at,
            ),
            key=offer.event_key(),
        )
        published_events += 1
    publisher.flush()

    publish_mode = "dry_run" if dry_run or not automq_bootstrap_servers else "kafka"
    manifest = write_run_manifest(
        lake_root,
        provider=provider,
        run_id=run_id,
        observed_date=observed_date,
        raw_ref=raw_ref,
        normalized_ref=normalized_ref,
        raw_offer_count=raw_offer_count,
        normalized_offer_count=len(normalized),
        published_events=published_events,
        unknown_gpu_names=unknown_gpu_names,
        publish_mode=publish_mode,
    )
    return IngestResult(
        provider=provider,
        run_id=run_id,
        raw_ref=raw_ref,
        normalized_ref=normalized_ref,
        raw_offer_count=raw_offer_count,
        normalized_offer_count=len(normalized),
        unknown_gpu_names=unknown_gpu_names,
        published_events=published_events,
        publish_mode=publish_mode,
        manifest_ref=manifest.manifest_ref,
    )


def _publisher(
    *,
    automq_bootstrap_servers: str | None,
    automq_config: dict[str, str] | None,
    dry_run: bool,
) -> Publisher:
    if dry_run or not automq_bootstrap_servers:
        return DryRunPublisher()
    config = kafka_config_from_env()
    if automq_config:
        config.update(automq_config)
    return KafkaPublisher(bootstrap_servers=automq_bootstrap_servers, config=config)
