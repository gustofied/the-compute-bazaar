"""Canonical records for GPU market data."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field, is_dataclass, replace
from datetime import date, datetime, timezone
from math import isfinite
from typing import Any

from ..contracts import MARKET_EVENT_CONTRACT


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


def _json_text(value: Any) -> str:
    return json.dumps(
        to_jsonable(value),
        sort_keys=True,
        separators=(",", ":"),
    )


@dataclass(frozen=True)
class EventEnvelope:
    """A durable event emitted to the AutoMQ/Kafka market log."""

    event_id: str
    event_type: str
    provider: str
    event_time: datetime
    ingest_time: datetime
    run_id: str
    trace_id: str
    raw_ref: str | None
    payload_hash: str
    payload: dict[str, Any]
    contract: str = MARKET_EVENT_CONTRACT

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
class OfferObservation:
    """One normalized observation of an offered GPU configuration."""

    provider: str
    source_offer_id: str
    observed_at: datetime
    gpu_raw_name: str
    gpu_model: str
    gpu_count: int
    vram_gb: float | None
    price_usd_instance_hr: float
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
    minimum_executable_price_usd_instance_hr: float | None = None
    required_resource_price_usd_instance_hr: float | None = None
    price_basis: str | None = None
    observation_id: str | None = None
    batch_id: str | None = None
    market_run_id: str | None = None
    observation_purpose: str = "scheduled"
    observation_resolution: str = "market_summary"
    selection_resolution: str = "gpu_type"
    query_scope: dict[str, Any] = field(default_factory=dict)
    response_complete: bool = True
    cloud_type: str | None = None
    location_ids: tuple[str, ...] = ()
    market_product_key: str | None = None
    selection_fingerprint: str | None = None
    native_selection: dict[str, Any] = field(default_factory=dict)
    raw_hash: str | None = None
    source_run_id: str | None = None
    source_manifest_ref: str | None = None
    source_normalized_ref: str | None = None
    methodology_version: str = "provider_normalization"
    schema_version: str = "offer_observation"

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("OfferObservation.observed_at must be timezone-aware")
        if self.gpu_count <= 0:
            raise ValueError("OfferObservation.gpu_count must be positive")
        if not isfinite(self.price_usd_instance_hr) or self.price_usd_instance_hr <= 0:
            raise ValueError(
                "OfferObservation.price_usd_instance_hr must be a positive rate"
            )
        if self.currency.upper() != "USD":
            raise ValueError("OfferObservation prices must be normalized to USD")
        if self.available_gpu_count is not None and self.available_gpu_count < 0:
            raise ValueError("OfferObservation.available_gpu_count cannot be negative")
        if not self.availability_status:
            raise ValueError("OfferObservation.availability_status cannot be empty")
        if (
            self.required_resource_price_usd_instance_hr is not None
            and self.required_resource_price_usd_instance_hr < 0
        ):
            raise ValueError(
                "OfferObservation.required_resource_price_usd_instance_hr cannot "
                "be negative"
            )
        if self.minimum_executable_price_usd_instance_hr is not None:
            if (
                self.minimum_executable_price_usd_instance_hr
                < self.price_usd_instance_hr
            ):
                raise ValueError(
                    "OfferObservation.minimum_executable_price_usd_instance_hr "
                    "cannot be below the instance rate"
                )
        if self.observation_purpose not in {
            "scheduled",
            "interactive",
            "preflight",
        }:
            raise ValueError("Unknown observation purpose")
        if self.observation_resolution not in {
            "market_summary",
            "deployment_option",
            "exact_offer",
        }:
            raise ValueError("Unknown observation resolution")
        if self.selection_resolution not in {
            "gpu_type",
            "datacenter_set",
            "exact_datacenter",
        }:
            raise ValueError("Unknown selection resolution")
        if self.market_product_key is None:
            object.__setattr__(self, "market_product_key", _market_product_key(self))

    def event_key(self) -> str:
        return f"{self.provider}:{self.gpu_model}:{self.source_offer_id}"

    @property
    def price_usd_gpu_hr(self) -> float:
        return self.price_usd_instance_hr / self.gpu_count

    @property
    def location(self) -> str:
        if len(self.location_ids) == 1:
            return self.location_ids[0]
        if self.location_ids:
            return f"{len(self.location_ids)} datacenters"
        return self.region or self.country or "global"

    @property
    def stock_status_value(self) -> str:
        return self.stock_status or self.availability_status

    @property
    def available(self) -> bool:
        return self.availability_status.lower() in {
            "available",
            "spot_available",
            "available_component_rate",
        }

    def with_context(self, **values: Any) -> OfferObservation:
        return replace(self, **values)

    def row(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "batch_id": self.batch_id,
            "market_run_id": self.market_run_id,
            "observation_purpose": self.observation_purpose,
            "observation_resolution": self.observation_resolution,
            "selection_resolution": self.selection_resolution,
            "observed_at": self.observed_at,
            "provider": self.provider,
            "source_connector": self.source_connector or self.provider,
            "source_offer_id": self.source_offer_id,
            "market_product_key": self.market_product_key,
            "gpu_raw_name": self.gpu_raw_name,
            "gpu_model": self.gpu_model,
            "gpu_count": self.gpu_count,
            "vram_gb": self.vram_gb,
            "price_usd_instance_hr": self.price_usd_instance_hr,
            "price_usd_gpu_hr": self.price_usd_gpu_hr,
            "currency": self.currency,
            "available_gpu_count_lower_bound": self.available_gpu_count,
            "is_available": self.available,
            "source_availability_status": self.availability_status,
            "source_stock_status": self.stock_status,
            "country": self.country,
            "region": self.region,
            "cloud_type": self.cloud_type,
            "location_ids_json": _json_text(list(self.location_ids)),
            "selection_fingerprint": self.selection_fingerprint,
            "native_selection_json": _json_text(self.native_selection),
            "query_scope_json": _json_text(self.query_scope),
            "response_complete": self.response_complete,
            "is_spot": self.is_spot,
            "is_secure": self.is_secure,
            "gpu_socket": self.gpu_socket,
            "price_is_variable": self.price_is_variable,
            "minimum_executable_price_usd_instance_hr": (
                self.minimum_executable_price_usd_instance_hr
            ),
            "required_resource_price_usd_instance_hr": (
                self.required_resource_price_usd_instance_hr
            ),
            "price_basis": self.price_basis,
            "raw_ref": self.raw_ref,
            "raw_hash": self.raw_hash,
            "source_run_id": self.source_run_id,
            "source_manifest_ref": self.source_manifest_ref,
            "source_normalized_ref": self.source_normalized_ref,
            "methodology_version": self.methodology_version,
            "schema_version": self.schema_version,
        }

    def to_dict(self) -> dict[str, Any]:
        return to_jsonable(self.row())


def _market_product_key(observation: OfferObservation) -> str:
    connector = observation.source_connector or observation.provider
    price_kind = "spot" if observation.is_spot else "ondemand"
    if connector == "runpod":
        gpu_ids = observation.native_selection.get("gpuTypeIds") or ()
        native = (
            next(iter(gpu_ids), None)
            or observation.metadata.get("gpu_type_id")
            or observation.source_offer_id.split(":", 1)[0]
        )
        return f"runpod:{_key_part(native)}:{price_kind}"
    if connector == "verda":
        native = (
            observation.native_selection.get("instance_type")
            or observation.metadata.get("instance_type")
            or observation.source_offer_id.split(":", 1)[0]
        )
        return f"verda:{_key_part(native)}:{price_kind}"
    return ":".join(
        (
            _key_part(connector),
            _key_part(observation.gpu_model),
            str(observation.gpu_count),
            price_kind,
        )
    )


def _key_part(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_")


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
    methodology_version: str = "compute_market_state"
    notes: str | None = None

    def event_key(self) -> str:
        return self.observation_id

    def to_dict(self) -> dict[str, Any]:
        return to_jsonable(self)
