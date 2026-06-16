"""Canonical records for GPU market data."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from typing import Any


SCHEMA_VERSION = "v1"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return {k: to_jsonable(v) for k, v in asdict(value).items()}
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    return value


@dataclass(frozen=True)
class EventEnvelope:
    """A durable event emitted to the AutoMQ/Kafka market log."""

    event_id: str
    event_type: str
    schema_version: str
    provider: str
    event_time: datetime
    ingest_time: datetime
    run_id: str
    trace_id: str
    raw_ref: str | None
    payload_hash: str
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return to_jsonable(self)


@dataclass(frozen=True)
class ProviderSnapshot:
    provider: str
    fetched_at: datetime
    raw_ref: str
    payload_hash: str
    offer_count: int
    query: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return to_jsonable(self)


@dataclass(frozen=True)
class GpuOffer:
    provider: str
    source_offer_id: str
    observed_at: datetime
    gpu_raw_name: str
    gpu_model: str
    gpu_count: int
    vram_gb: float | None
    price_usd_hr: float
    currency: str = "USD"
    country: str | None = None
    region: str | None = None
    is_spot: bool | None = None
    is_secure: bool | None = None
    availability_status: str = "available"
    raw_ref: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def event_key(self) -> str:
        return f"{self.provider}:{self.gpu_model}:{self.source_offer_id}"

    def to_dict(self) -> dict[str, Any]:
        return to_jsonable(self)


@dataclass(frozen=True)
class GpuIndexPrice:
    index_symbol: str
    window_start: datetime
    window_end: datetime
    methodology_version: str
    price_usd_hr: float
    executable_floor: float
    median_price: float | None
    trimmed_mean_price: float | None
    offer_count: int
    provider_count: int
    freshness_seconds: float | None
    calculation_hash: str

    def to_dict(self) -> dict[str, Any]:
        return to_jsonable(self)

