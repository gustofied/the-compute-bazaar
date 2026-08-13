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
    error: str | None = None

    @property
    def complete(self) -> bool:
        return self.error is None and 200 <= self.status_code < 300

    def bronze_record(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "request": {
                "method": "GET",
                "endpoint": self.endpoint,
                "parameters": self.parameters,
                "authentication": "x-api-key",
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
    """One marketplace offer in one location at one observation time."""

    observation_id: str
    run_id: str
    observed_at: datetime
    marketplace: str
    provider_id: str
    provider_name: str
    marketplace_offer_id: str
    gpu_name: str
    gpu_model: str | None
    gpu_count: int
    gpu_vram_gb: float | None
    total_vram_gb: float | None
    cpu_count: float | None
    memory_gb: float | None
    storage_gb: float | None
    deployment_type: str
    interconnect: str | None
    nvlink: bool | None
    cloud_init: bool | None
    country_code: str | None
    region_id: str
    region_name: str
    ask_usd_instance_hr: float
    ask_usd_gpu_hr: float
    available: bool
    os_images: tuple[str, ...] = ()
    raw_ref: str | None = None

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")
        if self.gpu_count < 1:
            raise ValueError("gpu_count must be positive")
        if self.ask_usd_instance_hr <= 0:
            raise ValueError("ask_usd_instance_hr must be positive")

    def row(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RejectedOffer:
    source_index: int
    reason: str
    marketplace_offer_id: str | None = None


@dataclass(frozen=True)
class NormalizedOffers:
    offers: tuple[GpuOffer, ...]
    rejected: tuple[RejectedOffer, ...] = ()


@dataclass(frozen=True)
class MarketRun:
    run_id: str
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
