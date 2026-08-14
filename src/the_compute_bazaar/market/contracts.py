"""Small contracts shared by market sources and the lake."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Literal


RunStatus = Literal["complete", "failed"]


def stable_id(*parts: object, length: int = 24) -> str:
    value = "\x1f".join(str(part) for part in parts)
    return hashlib.sha256(value.encode()).hexdigest()[:length]


def payload_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class SourceRead:
    source: str
    endpoint: str
    parameters: dict[str, str]
    observed_at: datetime
    status_code: int
    payload: Any
    elapsed_ms: float
    method: str = "GET"
    authentication: str | None = None
    error: str | None = None

    @property
    def complete(self) -> bool:
        return self.error is None and 200 <= self.status_code < 300

    def bronze_record(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "request": {
                "method": self.method,
                "endpoint": self.endpoint,
                "parameters": self.parameters,
                "authentication": self.authentication,
            },
            "response": {
                "status_code": self.status_code,
                "elapsed_ms": self.elapsed_ms,
                "complete": self.complete,
                "error": self.error,
                "payload_sha256": payload_hash(self.payload),
                "payload": self.payload,
            },
            "observed_at": self.observed_at,
        }


@dataclass(frozen=True)
class GpuOffer:
    """One GPU offer in one location at one observation time."""

    observation_id: str
    source_run_id: str
    observed_at: datetime
    source: str
    intermediary: str
    operator_id: str | None
    operator: str | None
    offer_id: str
    gpu_model: str | None
    gpu_count: int
    country_code: str | None
    region: str
    ask_usd_hr: float
    available: bool | None

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")
        if self.gpu_count < 1:
            raise ValueError("gpu_count must be positive")
        if self.ask_usd_hr <= 0:
            raise ValueError("ask_usd_hr must be positive")

    def row(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RejectedOffer:
    source_index: int
    reason: str
    offer_id: str | None = None


@dataclass(frozen=True)
class NormalizedOffers:
    offers: tuple[GpuOffer, ...]
    rejected: tuple[RejectedOffer, ...] = ()


@dataclass(frozen=True)
class MarketRun:
    source_run_id: str
    source: str
    observed_at: datetime
    status: RunStatus
    raw_ref: str
    silver_ref: str | None
    source_offer_count: int
    silver_row_count: int
    rejected: tuple[RejectedOffer, ...] = ()
    error: str | None = None
    manifest_ref: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def record(self) -> dict[str, Any]:
        return asdict(self)
