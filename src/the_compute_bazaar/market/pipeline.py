"""One source read into Bronze, Silver, and a run manifest."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Protocol

import pyarrow as pa

from .contracts import MarketRun, SourceRead, stable_id
from .lake import MarketLake


GPU_OFFER_SCHEMA = pa.schema(
    [
        ("observation_id", pa.string()),
        ("run_id", pa.string()),
        ("observed_at", pa.timestamp("us", tz="UTC")),
        ("marketplace", pa.string()),
        ("provider_id", pa.string()),
        ("provider_name", pa.string()),
        ("marketplace_offer_id", pa.string()),
        ("gpu_name", pa.string()),
        ("gpu_model", pa.string()),
        ("gpu_count", pa.int64()),
        ("gpu_vram_gb", pa.float64()),
        ("total_vram_gb", pa.float64()),
        ("cpu_count", pa.float64()),
        ("memory_gb", pa.float64()),
        ("storage_gb", pa.float64()),
        ("deployment_type", pa.string()),
        ("interconnect", pa.string()),
        ("nvlink", pa.bool_()),
        ("cloud_init", pa.bool_()),
        ("country_code", pa.string()),
        ("region_id", pa.string()),
        ("region_name", pa.string()),
        ("ask_usd_instance_hr", pa.float64()),
        ("ask_usd_gpu_hr", pa.float64()),
        ("available", pa.bool_()),
        ("os_images", pa.list_(pa.string())),
        ("raw_ref", pa.string()),
    ]
)


class MarketSource(Protocol):
    name: str

    def read(self, *, observed_at: datetime | None = None) -> SourceRead: ...

    def normalize(self, read: SourceRead, *, run_id: str, raw_ref: str): ...


@dataclass(frozen=True)
class MarketRunResult:
    run: MarketRun
    offers: tuple


class MarketPipeline:
    def __init__(self, lake: MarketLake) -> None:
        self.lake = lake

    def run(
        self,
        source: MarketSource,
        *,
        observed_at: datetime | None = None,
        run_id: str | None = None,
    ) -> MarketRunResult:
        observed_at = observed_at or datetime.now(UTC)
        run_id = (
            run_id
            or f"{source.name}-{observed_at:%Y%m%dT%H%M%S}-{stable_id(observed_at, length=8)}"
        )
        raw_ref = self.lake.bronze_ref(
            source=source.name, day=observed_at.date(), run_id=run_id
        )
        manifest_ref = self.lake.manifest_ref(
            source=source.name, day=observed_at.date(), run_id=run_id
        )
        read = source.read(observed_at=observed_at)
        self.lake.write_json(raw_ref, read.bronze_record())
        normalized = source.normalize(read, run_id=run_id, raw_ref=raw_ref)
        silver_ref = None
        if normalized.offers:
            silver_ref = self.lake.silver_ref(
                source=source.name, day=observed_at.date(), run_id=run_id
            )
            self.lake.write_parquet(
                silver_ref,
                (offer.row() for offer in normalized.offers),
                schema=GPU_OFFER_SCHEMA,
            )
        source_count = len(read.payload) if isinstance(read.payload, list) else 0
        run = MarketRun(
            run_id=run_id,
            source=source.name,
            observed_at=observed_at,
            status="complete" if read.complete else "failed",
            raw_ref=raw_ref,
            silver_ref=silver_ref,
            source_offer_count=source_count,
            silver_row_count=len(normalized.offers),
            rejected=normalized.rejected,
            error=read.error,
            manifest_ref=manifest_ref,
            metadata={"request_count": 1, "response_complete": read.complete},
        )
        self.lake.write_json(manifest_ref, run.record())
        return MarketRunResult(replace(run), normalized.offers)
