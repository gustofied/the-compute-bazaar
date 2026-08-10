"""Provider-native launch drafts built from revalidated live offers."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .models import LiveOffer, ProviderName
from .service import LiveOfferService


class LaunchPlan(BaseModel):
    """A request draft. It is never submitted to the provider."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    plan_id: str
    offer_id: str
    provider: ProviderName
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
            "provider": self.provider,
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
            "contract": "compute-bazaar.launch-plan.v1",
            "observed_at": self.observed_at,
            "rows": [self.row()],
            "plan": self.model_dump(mode="json"),
            "submitted": False,
        }


class LaunchPlanner:
    def __init__(self, service: LiveOfferService) -> None:
        self.service = service

    @classmethod
    def from_environment(cls) -> LaunchPlanner:
        return cls(LiveOfferService.from_environment())

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

        offer = self.service.inspect(offer_id)
        if not offer.available:
            raise ValueError(f"Offer {offer_id} is not currently available")
        if offer.provider == "runpod":
            return self._runpod_plan(
                offer,
                name=name,
                image=image,
                disk_gb=disk_gb,
                volume_gb=volume_gb,
            )
        return self._verda_plan(
            offer,
            name=name,
            image=image,
            ssh_key_ids=ssh_key_ids,
            disk_gb=disk_gb,
        )

    def _runpod_plan(
        self,
        offer: LiveOffer,
        *,
        name: str | None,
        image: str | None,
        disk_gb: int,
        volume_gb: int,
    ) -> LaunchPlan:
        request = {
            "cloudType": offer.selection["cloudType"],
            "computeType": "GPU",
            "gpuCount": offer.selection["gpuCount"],
            "gpuTypeIds": offer.selection["gpuTypeIds"],
            "dataCenterIds": offer.selection["dataCenterIds"],
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
        offer: LiveOffer,
        *,
        name: str | None,
        image: str | None,
        ssh_key_ids: tuple[str, ...],
        disk_gb: int,
    ) -> LaunchPlan:
        request: dict[str, Any] = {
            "instance_type": offer.selection["instance_type"],
            "location_code": offer.selection["location_code"],
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
        offer: LiveOffer,
        *,
        endpoint: str,
        request: dict[str, Any],
        missing: list[str],
        credentials_configured: bool,
        checks: tuple[str, ...],
    ) -> LaunchPlan:
        identity = json.dumps(
            {
                "offer_id": offer.offer_id,
                "observed_at": offer.observed_at.isoformat(),
                "request": request,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        plan_id = "launch-" + hashlib.sha256(identity.encode()).hexdigest()[:12]
        return LaunchPlan(
            plan_id=plan_id,
            offer_id=offer.offer_id,
            provider=offer.provider,
            operation=offer.selection["operation"],
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
