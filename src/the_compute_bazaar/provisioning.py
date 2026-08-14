"""Provider-native launch drafts built from preflight observations."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .offers import OfferService
from .prices.schemas import OfferObservation


class LaunchPlan(BaseModel):
    """A request draft. It is never submitted to the provider."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    plan_id: str
    offer_id: str
    candidate_observation_id: str | None = None
    preflight_observation_id: str
    preflight_batch_id: str
    market_product_key: str
    source_connector: str
    capacity_provider: str
    operation: Literal["create_pod", "create_instance"]
    endpoint: str
    observed_at: datetime
    gpu_model: str
    gpu_count: int = Field(ge=1)
    price_usd_gpu_hr: float = Field(gt=0)
    price_usd_instance_hr: float = Field(gt=0)
    cloud_type: str
    location: str
    status: Literal["draft", "ready_for_confirmation"]
    credentials_configured: bool
    required_inputs: tuple[str, ...] = ()
    operator_checks: tuple[str, ...] = ()
    request: dict[str, Any]

    def row(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "offer_id": self.offer_id,
            "candidate_observation_id": self.candidate_observation_id,
            "preflight_observation_id": self.preflight_observation_id,
            "source_connector": self.source_connector,
            "capacity_provider": self.capacity_provider,
            "gpu_model": self.gpu_model,
            "gpu_count": self.gpu_count,
            "price_usd_gpu_hr": self.price_usd_gpu_hr,
            "price_usd_instance_hr": self.price_usd_instance_hr,
            "cloud_type": self.cloud_type,
            "location": self.location,
            "status": self.status,
            "missing": ", ".join(self.required_inputs) or "none",
            "credentials_configured": self.credentials_configured,
            "observed_at": self.observed_at,
        }

    def payload(self) -> dict[str, Any]:
        return {
            "contract": "compute-bazaar.launch-plan",
            "observed_at": self.observed_at,
            "rows": [self.row()],
            "plan": self.model_dump(mode="json"),
            "submitted": False,
        }


class ProvisioningRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str
    plan_id: str
    candidate_observation_id: str | None = None
    preflight_observation_id: str
    preflight_batch_id: str
    source_offer_id: str
    market_product_key: str
    acquisition_connector: str
    capacity_provider: str
    operation: str
    gpu_model: str
    gpu_count: int = Field(ge=1)
    selected_price_usd_gpu_hr: float = Field(gt=0)
    selected_price_usd_instance_hr: float = Field(gt=0)
    max_hourly_usd: float = Field(gt=0)
    runtime_minutes: int = Field(ge=5, le=120)
    expected_max_cost_usd: float = Field(gt=0)
    request_hash: str
    provider_request: dict[str, Any]
    created_at: datetime
    state: Literal["pending", "succeeded", "failed", "uncertain"] = "pending"

    @classmethod
    def from_plan(
        cls,
        plan: LaunchPlan,
        *,
        runtime_minutes: int,
        max_hourly_usd: float,
        created_at: datetime | None = None,
    ) -> ProvisioningRequest:
        created_at = created_at or datetime.now(UTC)
        request_payload = {
            "plan_id": plan.plan_id,
            "candidate_observation_id": plan.candidate_observation_id,
            "preflight_observation_id": plan.preflight_observation_id,
            "runtime_minutes": runtime_minutes,
            "max_hourly_usd": max_hourly_usd,
            "provider_request": plan.request,
        }
        encoded = json.dumps(
            request_payload, sort_keys=True, separators=(",", ":")
        ).encode()
        request_hash = hashlib.sha256(encoded).hexdigest()
        return cls(
            request_id=f"request-{request_hash[:16]}",
            plan_id=plan.plan_id,
            candidate_observation_id=plan.candidate_observation_id,
            preflight_observation_id=plan.preflight_observation_id,
            preflight_batch_id=plan.preflight_batch_id,
            source_offer_id=plan.offer_id,
            market_product_key=plan.market_product_key,
            acquisition_connector=plan.source_connector,
            capacity_provider=plan.capacity_provider,
            operation=plan.operation,
            gpu_model=plan.gpu_model,
            gpu_count=plan.gpu_count,
            selected_price_usd_gpu_hr=plan.price_usd_gpu_hr,
            selected_price_usd_instance_hr=plan.price_usd_instance_hr,
            max_hourly_usd=max_hourly_usd,
            runtime_minutes=runtime_minutes,
            expected_max_cost_usd=round(
                plan.price_usd_instance_hr * runtime_minutes / 60, 4
            ),
            request_hash=request_hash,
            provider_request=plan.request,
            created_at=created_at,
        )


class ProvisioningAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    attempt_id: str
    request_id: str
    attempt_number: int = Field(ge=1)
    state: Literal["pending", "succeeded", "failed", "uncertain"]
    started_at: datetime
    completed_at: datetime | None = None
    provider_resource_id: str | None = None
    error: str | None = None


class Allocation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    allocation_id: str
    request_id: str
    successful_attempt_id: str
    candidate_observation_id: str | None = None
    preflight_observation_id: str
    source: str
    intermediary: str
    operator: str | None = None
    offer_id: str
    source_resource_id: str
    state: str
    price_usd_gpu_hr: float = Field(gt=0)
    price_usd_instance_hr: float = Field(gt=0)
    created_at: datetime
    terminate_at: datetime | None = None
    terminated_at: datetime | None = None
    updated_at: datetime


class LaunchPlanner:
    def __init__(self, service: OfferService) -> None:
        self.service = service

    @classmethod
    def from_environment(cls) -> LaunchPlanner:
        return cls(OfferService.from_environment())

    def plan(
        self,
        offer_id: str,
        *,
        name: str | None = None,
        image: str | None = None,
        ssh_key_ids: tuple[str, ...] = (),
        disk_gb: int = 50,
        volume_gb: int = 0,
    ) -> LaunchPlan:
        if disk_gb < 1:
            raise ValueError("disk_gb must be at least 1")
        if volume_gb < 0:
            raise ValueError("volume_gb cannot be negative")

        candidate_observation_id = self.service.candidate_observation_id(offer_id)
        offer = self.service.inspect(offer_id)
        if not offer.available:
            raise ValueError(f"Offer {offer_id} is not currently available")
        connector = offer.source_connector or offer.provider
        if connector == "runpod":
            return self._runpod_plan(
                offer,
                candidate_observation_id=candidate_observation_id,
                name=name,
                image=image,
                disk_gb=disk_gb,
                volume_gb=volume_gb,
            )
        if connector != "verda":
            raise ValueError(f"No acquisition connector for {connector}")
        return self._verda_plan(
            offer,
            candidate_observation_id=candidate_observation_id,
            name=name,
            image=image,
            ssh_key_ids=ssh_key_ids,
            disk_gb=disk_gb,
        )

    def _runpod_plan(
        self,
        offer: OfferObservation,
        *,
        candidate_observation_id: str | None,
        name: str | None,
        image: str | None,
        disk_gb: int,
        volume_gb: int,
    ) -> LaunchPlan:
        request = {
            "cloudType": offer.native_selection["cloudType"],
            "computeType": "GPU",
            "gpuCount": offer.native_selection["gpuCount"],
            "gpuTypeIds": offer.native_selection["gpuTypeIds"],
            "dataCenterIds": offer.native_selection["dataCenterIds"],
            "dataCenterPriority": "availability",
            "containerDiskInGb": disk_gb,
            "volumeInGb": volume_gb,
            "volumeMountPath": "/workspace",
            "ports": ["22/tcp"],
            "supportPublicIp": True,
            "interruptible": False,
        }
        missing: list[str] = []
        if name:
            request["name"] = name
        else:
            missing.append("name")
        if image:
            request["imageName"] = image
        else:
            missing.append("image")
        return self._build(
            offer,
            candidate_observation_id=candidate_observation_id,
            endpoint="https://rest.runpod.io/v1/pods",
            request=request,
            missing=missing,
            credentials_configured=bool(self.service.runpod_api_key),
            checks=(
                "RunPod account has the intended SSH public key",
                "Confirm the current provider price before creation",
            ),
        )

    def _verda_plan(
        self,
        offer: OfferObservation,
        *,
        candidate_observation_id: str | None,
        name: str | None,
        image: str | None,
        ssh_key_ids: tuple[str, ...],
        disk_gb: int,
    ) -> LaunchPlan:
        request: dict[str, Any] = {
            "instance_type": offer.native_selection["instance_type"],
            "location_code": offer.native_selection["location_code"],
            "description": "Compute Bazaar launch",
            "contract": "PAY_AS_YOU_GO",
            "is_spot": False,
            "pricing": "FIXED_PRICE",
        }
        missing: list[str] = []
        if name:
            request["hostname"] = name
            request["os_volume"] = {
                "name": f"{name}-os",
                "size": disk_gb,
            }
        else:
            missing.append("name")
        if image:
            request["image"] = image
        else:
            missing.append("image")
        if ssh_key_ids:
            request["ssh_key_ids"] = list(ssh_key_ids)
        else:
            missing.append("ssh_key_id")
        return self._build(
            offer,
            candidate_observation_id=candidate_observation_id,
            endpoint="https://api.verda.com/v1/instances",
            request=request,
            missing=missing,
            credentials_configured=bool(
                self.service.verda_access_token
                or (self.service.verda_client_id and self.service.verda_client_secret)
            ),
            checks=("Confirm the current provider price before creation",),
        )

    @staticmethod
    def _build(
        offer: OfferObservation,
        *,
        candidate_observation_id: str | None,
        endpoint: str,
        request: dict[str, Any],
        missing: list[str],
        credentials_configured: bool,
        checks: tuple[str, ...],
    ) -> LaunchPlan:
        if (
            not offer.observation_id
            or not offer.batch_id
            or not offer.market_product_key
        ):
            raise ValueError("Preflight observation has no lineage")
        identity = json.dumps(
            {
                "offer_id": offer.source_offer_id,
                "observed_at": offer.observed_at.isoformat(),
                "request": request,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        plan_id = "launch-" + hashlib.sha256(identity.encode()).hexdigest()[:12]
        return LaunchPlan(
            plan_id=plan_id,
            offer_id=offer.source_offer_id,
            candidate_observation_id=candidate_observation_id,
            preflight_observation_id=offer.observation_id,
            preflight_batch_id=offer.batch_id,
            market_product_key=offer.market_product_key,
            source_connector=offer.source_connector or offer.provider,
            capacity_provider=offer.provider,
            operation=offer.native_selection["operation"],
            endpoint=endpoint,
            observed_at=offer.observed_at,
            gpu_model=offer.gpu_model,
            gpu_count=offer.gpu_count,
            price_usd_gpu_hr=offer.price_usd_gpu_hr,
            price_usd_instance_hr=offer.price_usd_instance_hr,
            cloud_type=offer.cloud_type,
            location=offer.location,
            status="draft" if missing else "ready_for_confirmation",
            credentials_configured=credentials_configured,
            required_inputs=tuple(missing),
            operator_checks=checks,
            request=request,
        )
