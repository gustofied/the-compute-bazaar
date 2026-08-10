"""Typed contract for offers fetched directly from compute providers."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


ProviderName = Literal["runpod", "verda"]


class LiveOffer(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    offer_id: str
    provider: ProviderName
    native_offer_id: str
    offer_kind: Literal["deployment_requirement", "instance_location"]
    observed_at: datetime
    gpu_model: str
    gpu_name: str
    gpu_count: int = Field(ge=1)
    vram_gb: float | None = Field(default=None, gt=0)
    price_usd_gpu_hr: float = Field(gt=0)
    price_usd_instance_hr: float = Field(gt=0)
    cloud_type: str
    location: str
    location_ids: tuple[str, ...] = ()
    stock_status: str
    available: bool
    selection: dict[str, Any]

    @model_validator(mode="after")
    def validate_observation(self) -> LiveOffer:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        return self

    def row(self) -> dict[str, Any]:
        return {
            "offer_id": self.offer_id,
            "provider": self.provider,
            "gpu_model": self.gpu_model,
            "gpu_name": self.gpu_name,
            "gpu_count": self.gpu_count,
            "vram_gb": self.vram_gb,
            "price_usd_gpu_hr": self.price_usd_gpu_hr,
            "price_usd_instance_hr": self.price_usd_instance_hr,
            "cloud_type": self.cloud_type,
            "location": self.location,
            "location_count": len(self.location_ids),
            "stock_status": self.stock_status,
            "available": self.available,
            "native_offer_id": self.native_offer_id,
            "observed_at": self.observed_at,
        }


class ProviderStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: ProviderName
    status: Literal["ok", "credentials_required", "error"]
    offer_count: int = Field(default=0, ge=0)
    message: str | None = None


class LiveOfferResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    observed_at: datetime
    offers: tuple[LiveOffer, ...]
    providers: tuple[ProviderStatus, ...]

    def payload(self) -> dict[str, Any]:
        return {
            "contract": "compute-bazaar.live-offers.v1",
            "observed_at": self.observed_at,
            "providers": [status.model_dump(mode="json") for status in self.providers],
            "rows": [offer.row() for offer in self.offers],
        }
