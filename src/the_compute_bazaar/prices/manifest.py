"""Run manifest helpers for GPU offer ingestion."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .schemas import utc_now
from .storage import read_json, write_json


MANIFEST_VERSION = "v1"
TABLE_NAME = "gpu_offers"


@dataclass(frozen=True)
class GpuOffersRunManifest:
    provider: str
    run_id: str
    observed_at: str
    raw_ref: str
    normalized_ref: str | None
    raw_offer_count: int
    normalized_offer_count: int
    published_events: int
    unknown_gpu_names: list[str]
    publish_mode: str = "kafka"
    manifest_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest_version": MANIFEST_VERSION,
            "table": TABLE_NAME,
            "provider": self.provider,
            "run_id": self.run_id,
            "observed_at": self.observed_at,
            "raw_ref": self.raw_ref,
            "normalized_ref": self.normalized_ref,
            "raw_offer_count": self.raw_offer_count,
            "normalized_offer_count": self.normalized_offer_count,
            "published_events": self.published_events,
            "publish_mode": self.publish_mode,
            "unknown_gpu_names": self.unknown_gpu_names,
            "manifest_ref": self.manifest_ref,
        }


def latest_manifest_ref(lake_root: str, *, provider: str = "vast") -> str:
    return "/".join(
        [
            lake_root.rstrip("/"),
            "_manifests",
            TABLE_NAME,
            f"provider={provider}",
            "latest.json",
        ]
    )


def run_manifest_ref(lake_root: str, *, provider: str, observed_date: str, run_id: str) -> str:
    return "/".join(
        [
            lake_root.rstrip("/"),
            "_manifests",
            TABLE_NAME,
            f"provider={provider}",
            f"date={observed_date}",
            f"run_id={run_id}.json",
        ]
    )


def write_run_manifest(
    lake_root: str,
    *,
    provider: str,
    run_id: str,
    observed_date: str,
    raw_ref: str,
    normalized_ref: str | None,
    raw_offer_count: int,
    normalized_offer_count: int,
    published_events: int,
    unknown_gpu_names: list[str],
    publish_mode: str = "kafka",
) -> GpuOffersRunManifest:
    manifest_ref = run_manifest_ref(
        lake_root,
        provider=provider,
        observed_date=observed_date,
        run_id=run_id,
    )
    manifest = GpuOffersRunManifest(
        provider=provider,
        run_id=run_id,
        observed_at=utc_now().isoformat(),
        raw_ref=raw_ref,
        normalized_ref=normalized_ref,
        raw_offer_count=raw_offer_count,
        normalized_offer_count=normalized_offer_count,
        published_events=published_events,
        unknown_gpu_names=unknown_gpu_names,
        publish_mode=publish_mode,
        manifest_ref=manifest_ref,
    )
    payload = manifest.to_dict()
    write_json(manifest_ref, payload)
    write_json(latest_manifest_ref(lake_root, provider=provider), payload)
    return manifest


def read_latest_manifest(lake_root: str, *, provider: str = "vast") -> dict[str, Any]:
    return dict(read_json(latest_manifest_ref(lake_root, provider=provider)))
