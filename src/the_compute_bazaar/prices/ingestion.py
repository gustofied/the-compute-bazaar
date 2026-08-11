"""Durable ingestion lifecycle shared by every market source."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .automq import DryRunPublisher, KafkaPublisher, Publisher, kafka_config_from_env
from .events import make_event, sha256_json, sha256_text
from .manifest import run_manifest_ref, write_run_manifest
from .schemas import ComputeMarketState, OfferObservation, ProviderSnapshot
from .storage import (
    table_partition,
    write_json,
    write_offer_observations_parquet,
    write_parquet_rows,
)


@dataclass(frozen=True)
class IngestResult:
    provider: str
    run_id: str
    raw_ref: str
    normalized_ref: str | None
    raw_offer_count: int
    normalized_observation_count: int
    unknown_gpu_names: list[str]
    published_events: int
    publish_mode: str
    market_state_ref: str | None = None
    market_state_observation_count: int = 0
    manifest_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "run_id": self.run_id,
            "raw_ref": self.raw_ref,
            "normalized_ref": self.normalized_ref,
            "raw_offer_count": self.raw_offer_count,
            "normalized_observation_count": self.normalized_observation_count,
            "unknown_gpu_names": self.unknown_gpu_names,
            "published_events": self.published_events,
            "publish_mode": self.publish_mode,
            "market_state_ref": self.market_state_ref,
            "market_state_observation_count": self.market_state_observation_count,
            "manifest_ref": self.manifest_ref,
        }


def persist_provider_snapshot(
    *,
    provider: str,
    run_id: str,
    trace_id: str,
    observed_at: datetime,
    lake_root: str,
    raw_ref: str,
    raw_payload: Any,
    raw_offer_count: int,
    normalized: list[OfferObservation],
    unknown_gpu_names: list[str],
    snapshot_query: dict[str, Any],
    automq_bootstrap_servers: str | None,
    automq_config: dict[str, str] | None,
    topic_prefix: str,
    dry_run: bool,
    market_state: list[ComputeMarketState] | None = None,
) -> IngestResult:
    """Persist one source observation and publish its event tape records."""
    observed_date = observed_at.date().isoformat()
    write_json(raw_ref, raw_payload)
    raw_hash = sha256_json(raw_payload)
    normalized_ref = (
        table_partition(
            lake_root,
            table="silver/offer_observations",
            observed_date=observed_date,
            provider=provider,
            run_id=run_id,
            filename="observations.parquet",
        )
        if normalized
        else None
    )
    source_manifest_ref = run_manifest_ref(
        lake_root,
        provider=provider,
        observed_date=observed_date,
        run_id=run_id,
    )
    normalized = [
        observation.with_context(
            observation_id="obs-"
            + sha256_text(f"{run_id}\x1f{provider}\x1f{observation.source_offer_id}")[
                :20
            ],
            batch_id=run_id,
            market_run_id=trace_id,
            observation_purpose="scheduled",
            observation_resolution="market_summary",
            selection_resolution="gpu_type",
            query_scope=snapshot_query,
            response_complete=True,
            source_connector=observation.source_connector or provider,
            selection_fingerprint=sha256_text(
                f"{provider}\x1f{observation.source_offer_id}"
            )[:20],
            raw_ref=raw_ref,
            raw_hash=raw_hash,
            source_run_id=run_id,
            source_manifest_ref=source_manifest_ref,
            source_normalized_ref=normalized_ref,
            methodology_version="scheduled_provider_normalization",
        )
        for observation in normalized
    ]
    if normalized_ref:
        write_offer_observations_parquet(normalized_ref, normalized)

    market_state_rows = list(market_state or [])
    market_state_ref: str | None = None
    if market_state_rows:
        market_state_ref = table_partition(
            lake_root,
            table="silver/compute_market_state",
            observed_date=observed_date,
            provider=provider,
            run_id=run_id,
            filename="observations.parquet",
        )
        state_manifest_ref = run_manifest_ref(
            lake_root,
            provider=provider,
            observed_date=observed_date,
            run_id=run_id,
        )
        write_parquet_rows(
            market_state_ref,
            [
                {
                    **observation.to_dict(),
                    "source_run_id": run_id,
                    "source_manifest_ref": state_manifest_ref,
                    "source_normalized_ref": normalized_ref,
                    "source_market_state_ref": market_state_ref,
                }
                for observation in market_state_rows
            ],
        )

    publisher = _publisher(
        automq_bootstrap_servers=automq_bootstrap_servers,
        automq_config=automq_config,
        dry_run=dry_run,
    )
    snapshot = ProviderSnapshot(
        provider=provider,
        fetched_at=observed_at,
        raw_ref=raw_ref,
        payload_hash=raw_hash,
        offer_count=raw_offer_count,
        query=snapshot_query,
    )
    publisher.publish(
        f"{topic_prefix}.provider_snapshot",
        make_event(
            event_type="gpu.provider_snapshot",
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
            f"{topic_prefix}.offer_observation",
            make_event(
                event_type="gpu.offer_observation",
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
    for observation in market_state_rows:
        publisher.publish(
            f"{topic_prefix}.market_state_observation",
            make_event(
                event_type="gpu.market_state_observation",
                provider=provider,
                payload=observation.to_dict(),
                run_id=run_id,
                trace_id=trace_id,
                raw_ref=raw_ref,
                event_time=observation.observed_at,
            ),
            key=observation.event_key(),
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
        normalized_observation_count=len(normalized),
        published_events=published_events,
        unknown_gpu_names=unknown_gpu_names,
        publish_mode=publish_mode,
        market_state_ref=market_state_ref,
        market_state_observation_count=len(market_state_rows),
    )
    return IngestResult(
        provider=provider,
        run_id=run_id,
        raw_ref=raw_ref,
        normalized_ref=normalized_ref,
        raw_offer_count=raw_offer_count,
        normalized_observation_count=len(normalized),
        unknown_gpu_names=unknown_gpu_names,
        published_events=published_events,
        publish_mode=publish_mode,
        market_state_ref=market_state_ref,
        market_state_observation_count=len(market_state_rows),
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
