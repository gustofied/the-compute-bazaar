"""End-to-end provider ingestion pipelines."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from typing import Any

from .automq import DryRunPublisher, KafkaPublisher, Publisher, kafka_config_from_env
from .events import make_event, new_run_id, sha256_json
from .manifest import write_run_manifest
from .providers.lium import LiumClient, normalize_executors
from .providers.rate_cards import (
    DEFAULT_RATE_CARD_PROVIDER,
    normalize_rate_card_entries,
    rate_card_entries,
    rate_card_raw_payload,
)
from .providers.vast import VastClient, default_market_query, extract_offers, normalize_offers
from .schemas import ProviderSnapshot, utc_now
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

    client = VastClient(api_key=api_key or os.getenv("VAST_API_KEY"), **({"api_base": api_base} if api_base else {}))
    effective_query = query if query is not None else default_market_query()
    payload = client.search_bundles(query=effective_query)
    raw_payload_hash = sha256_json(payload)
    offers = extract_offers(payload)

    raw_ref = date_partition(
        raw_root,
        provider=provider,
        observed_date=observed_date,
        run_id=run_id,
        filename="bundles.json",
    )
    write_json(raw_ref, payload)

    normalized, unknown_gpu_names = normalize_offers(offers, observed_at=observed_at, raw_ref=raw_ref)
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
        query=effective_query if isinstance(effective_query, dict) else {"q": effective_query},
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
    publisher.publish(f"{topic_prefix}.provider_snapshot.v1", snapshot_event, key=provider)
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
        publisher.publish(f"{topic_prefix}.normalized_offer.v1", event, key=offer.event_key())
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

    client = LiumClient(api_key=api_key or os.getenv("LIUM_API_KEY"), **({"api_base": api_base} if api_base else {}))
    fetched = client.fetch_executor_pages(query=query, paginate=paginate, max_pages=max_pages)
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

    normalized, unknown_gpu_names = normalize_executors(executors, observed_at=observed_at, raw_ref=raw_ref)
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
        query={**(query or {}), "paginate": paginate, "max_pages": max_pages if paginate else None},
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
    publisher.publish(f"{topic_prefix}.provider_snapshot.v1", snapshot_event, key=provider)
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
        publisher.publish(f"{topic_prefix}.normalized_offer.v1", event, key=offer.event_key())
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

    normalized, unknown_gpu_names = normalize_rate_card_entries(entries, observed_at=observed_at, raw_ref=raw_ref)
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
    publisher.publish(f"{topic_prefix}.provider_snapshot.v1", snapshot_event, key=provider_name)
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
        publisher.publish(f"{topic_prefix}.normalized_offer.v1", event, key=offer.event_key())
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
