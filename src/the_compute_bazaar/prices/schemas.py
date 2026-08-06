"""Canonical records for GPU market data."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date, datetime, timezone
from math import isfinite
from typing import Any


SCHEMA_VERSION = "v1"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_jsonable(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
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
    """One normalized offer; ``price_usd_hr`` is the full configuration rate."""

    provider: str
    source_offer_id: str
    observed_at: datetime
    gpu_raw_name: str
    gpu_model: str
    gpu_count: int
    vram_gb: float | None
    price_usd_hr: float
    available_gpu_count: int | None = None
    source_connector: str | None = None
    currency: str = "USD"
    country: str | None = None
    region: str | None = None
    is_spot: bool | None = None
    is_secure: bool | None = None
    availability_status: str = "available"
    raw_ref: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    gpu_socket: str | None = None
    stock_status: str | None = None
    price_is_variable: bool | None = None
    minimum_executable_price_usd_hr: float | None = None
    required_resource_price_usd_hr: float | None = None
    price_basis: str | None = None

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("GpuOffer.observed_at must be timezone-aware")
        if self.gpu_count <= 0:
            raise ValueError("GpuOffer.gpu_count must be positive")
        if not isfinite(self.price_usd_hr) or self.price_usd_hr <= 0:
            raise ValueError("GpuOffer.price_usd_hr must be a positive instance rate")
        if self.currency.upper() != "USD":
            raise ValueError("GpuOffer prices must be normalized to USD")
        if self.available_gpu_count is not None and self.available_gpu_count < 0:
            raise ValueError("GpuOffer.available_gpu_count cannot be negative")
        if not self.availability_status:
            raise ValueError("GpuOffer.availability_status cannot be empty")
        if (
            self.required_resource_price_usd_hr is not None
            and self.required_resource_price_usd_hr < 0
        ):
            raise ValueError(
                "GpuOffer.required_resource_price_usd_hr cannot be negative"
            )
        if self.minimum_executable_price_usd_hr is not None:
            if self.minimum_executable_price_usd_hr < self.price_usd_hr:
                raise ValueError(
                    "GpuOffer.minimum_executable_price_usd_hr cannot be below "
                    "the instance rate"
                )

    def event_key(self) -> str:
        return f"{self.provider}:{self.gpu_model}:{self.source_offer_id}"

    def to_dict(self) -> dict[str, Any]:
        return to_jsonable(self)


@dataclass(frozen=True)
class ComputeMarketState:
    """A source-defined observation about rental or deployable capacity."""

    observation_id: str
    observed_at: datetime
    resource_market: str
    resource_type: str
    provider: str
    source_connector: str
    source_role: str
    measurement_kind: str
    measurement_scope: str
    unit: str
    total_units: float | None
    rented_units: float | None
    available_units: float | None
    pending_units: float | None
    rented_share: float | None
    available_share: float | None
    stock_status: str | None
    count_precision: str
    numerator_definition: str
    denominator_definition: str
    aggregation_eligible: bool
    aggregation_exclusion_reason: str | None
    source_url: str
    raw_ref: str | None
    methodology_version: str = "compute_market_state_v1"
    notes: str | None = None

    def event_key(self) -> str:
        return self.observation_id

    def to_dict(self) -> dict[str, Any]:
        return to_jsonable(self)
