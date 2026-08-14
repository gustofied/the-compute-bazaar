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
        ("source_run_id", pa.string()),
        ("observed_at", pa.timestamp("us", tz="UTC")),
        ("source", pa.string()),
        ("intermediary", pa.string()),
        ("operator_id", pa.string()),
        ("operator", pa.string()),
        ("offer_id", pa.string()),
        ("gpu_model", pa.string()),
        ("gpu_count", pa.int64()),
        ("country_code", pa.string()),
        ("region", pa.string()),
        ("ask_usd_hr", pa.float64()),
        ("available", pa.bool_()),
    ]
)


class MarketSource(Protocol):
    name: str

    def read(self, *, observed_at: datetime | None = None) -> SourceRead: ...

    def normalize(self, read: SourceRead, *, source_run_id: str): ...


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
        source_run_id: str | None = None,
    ) -> MarketRunResult:
        observed_at = observed_at or datetime.now(UTC)
        source_run_id = (
            source_run_id
            or f"{source.name}-{observed_at:%Y%m%dT%H%M%S}-{stable_id(observed_at, length=8)}"
        )
        read = source.read(observed_at=observed_at)
        return self.record(source, read, source_run_id=source_run_id)

    def record(
        self,
        source: MarketSource,
        read: SourceRead,
        *,
        source_run_id: str,
    ) -> MarketRunResult:
        observed_at = read.observed_at
        raw_ref = self.lake.bronze_ref(
            source=source.name,
            day=observed_at.date(),
            source_run_id=source_run_id,
        )
        manifest_ref = self.lake.manifest_ref(
            source=source.name,
            day=observed_at.date(),
            source_run_id=source_run_id,
        )
        self.lake.write_json(raw_ref, read.bronze_record())
        normalized = source.normalize(read, source_run_id=source_run_id)
        silver_ref = self.lake.silver_ref(
            source=source.name,
            day=observed_at.date(),
            source_run_id=source_run_id,
        )
        self.lake.write_parquet(
            silver_ref,
            (offer.row() for offer in normalized.offers),
            schema=GPU_OFFER_SCHEMA,
        )
        source_count = len(read.payload) if isinstance(read.payload, list) else 0
        run = MarketRun(
            source_run_id=source_run_id,
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
