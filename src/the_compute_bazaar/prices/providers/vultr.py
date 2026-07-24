"""Vultr public GPU plan pricing and regional availability adapter."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests

from ..normalize import canonical_gpu_model
from ..schemas import GpuOffer
from .http import retrying_session


DEFAULT_VULTR_API_BASE = "https://api.vultr.com/v2"


@dataclass(frozen=True)
class VultrCatalogFetch:
    raw_payload: dict[str, Any]
    plans: list[dict[str, Any]]
    available_regions_by_plan: dict[str, list[str]]


class VultrClient:
    def __init__(
        self,
        *,
        api_base: str = DEFAULT_VULTR_API_BASE,
        session: requests.Session | None = None,
    ) -> None:
        self.api_base = api_base.rstrip("/")
        self.session = session or retrying_session()

    def fetch_gpu_catalog(self) -> VultrCatalogFetch:
        plans_payload = self._get("/plans", params={"per_page": 500})
        metal_payload = self._get("/plans-metal", params={"per_page": 500})
        regions_payload = self._get("/regions", params={"per_page": 500})

        plans = _extract_gpu_plans(plans_payload, metal_payload)
        region_ids = _extract_region_ids(regions_payload)
        availability_payloads: dict[str, Any] = {}
        regions_by_plan: dict[str, list[str]] = {}
        for region_id in region_ids:
            payload = self._get(f"/regions/{region_id}/availability", params={})
            availability_payloads[region_id] = payload
            for plan_id in _extract_available_plan_ids(payload):
                regions_by_plan.setdefault(plan_id, []).append(region_id)

        available_regions_by_plan = {
            plan_id: sorted(regions) for plan_id, regions in regions_by_plan.items()
        }
        return VultrCatalogFetch(
            raw_payload={
                "mode": "public_plan_prices_and_regional_availability",
                "plans_payload": plans_payload,
                "metal_plans_payload": metal_payload,
                "regions_payload": regions_payload,
                "availability_payloads": availability_payloads,
                "gpu_plan_count": len(plans),
                "region_count": len(region_ids),
            },
            plans=plans,
            available_regions_by_plan=available_regions_by_plan,
        )

    def _get(self, path: str, *, params: dict[str, Any]) -> Any:
        response = self.session.get(
            f"{self.api_base}{path}",
            params=params,
            headers={"Accept": "application/json"},
            timeout=60,
        )
        response.raise_for_status()
        return response.json()


def normalize_gpu_plans(
    plans: Iterable[Mapping[str, Any]],
    *,
    available_regions_by_plan: Mapping[str, list[str]],
    observed_at: datetime,
    raw_ref: str | None,
) -> tuple[list[GpuOffer], list[str]]:
    normalized: list[GpuOffer] = []
    unknown_gpu_names: list[str] = []

    for plan in plans:
        plan_id = str(plan.get("id") or "").strip()
        gpu_name = _gpu_name(plan)
        gpu_count = _whole_gpu_count(plan.get("gpu_count"))
        if not plan_id or not gpu_name or gpu_count is None:
            continue
        total_vram_gb = _float_or_none(plan.get("gpu_vram_gb"))
        vram_gb = total_vram_gb / gpu_count if total_vram_gb else None
        gpu_model = canonical_gpu_model(
            gpu_name,
            vram_gb * 1024 if vram_gb is not None else None,
        )
        if not gpu_model:
            unknown_gpu_names.append(gpu_name)
            continue
        if gpu_count > 1:
            gpu_model = f"{gpu_model}_x{gpu_count}"

        live_regions = sorted(set(available_regions_by_plan.get(plan_id, [])))
        on_demand_price = _float_or_none(plan.get("hourly_cost"))
        preemptible_price = _float_or_none(plan.get("hourly_cost_preemptible"))
        deploy_ondemand = plan.get("deploy_ondemand") is True
        deploy_preemptible = plan.get("deploy_preemptible") is True

        if live_regions:
            for region in live_regions:
                if deploy_ondemand and on_demand_price and on_demand_price > 0:
                    normalized.append(
                        _offer(
                            plan=plan,
                            plan_id=plan_id,
                            gpu_name=gpu_name,
                            gpu_model=gpu_model,
                            gpu_count=gpu_count,
                            vram_gb=vram_gb,
                            price=on_demand_price,
                            region=region,
                            is_spot=False,
                            availability_status="available",
                            available_gpu_count=gpu_count,
                            observed_at=observed_at,
                            raw_ref=raw_ref,
                        )
                    )
                if deploy_preemptible and preemptible_price and preemptible_price > 0:
                    normalized.append(
                        _offer(
                            plan=plan,
                            plan_id=plan_id,
                            gpu_name=gpu_name,
                            gpu_model=gpu_model,
                            gpu_count=gpu_count,
                            vram_gb=vram_gb,
                            price=preemptible_price,
                            region=region,
                            is_spot=True,
                            availability_status="spot_available",
                            available_gpu_count=(
                                gpu_count if not deploy_ondemand else None
                            ),
                            observed_at=observed_at,
                            raw_ref=raw_ref,
                        )
                    )
            continue

        if deploy_ondemand and on_demand_price and on_demand_price > 0:
            normalized.append(
                _offer(
                    plan=plan,
                    plan_id=plan_id,
                    gpu_name=gpu_name,
                    gpu_model=gpu_model,
                    gpu_count=gpu_count,
                    vram_gb=vram_gb,
                    price=on_demand_price,
                    region=None,
                    is_spot=False,
                    availability_status="unavailable",
                    available_gpu_count=None,
                    observed_at=observed_at,
                    raw_ref=raw_ref,
                )
            )
        if deploy_preemptible and preemptible_price and preemptible_price > 0:
            normalized.append(
                _offer(
                    plan=plan,
                    plan_id=plan_id,
                    gpu_name=gpu_name,
                    gpu_model=gpu_model,
                    gpu_count=gpu_count,
                    vram_gb=vram_gb,
                    price=preemptible_price,
                    region=None,
                    is_spot=True,
                    availability_status="spot_price_observed",
                    available_gpu_count=None,
                    observed_at=observed_at,
                    raw_ref=raw_ref,
                )
            )

    return normalized, sorted(set(unknown_gpu_names))


def _offer(
    *,
    plan: Mapping[str, Any],
    plan_id: str,
    gpu_name: str,
    gpu_model: str,
    gpu_count: int,
    vram_gb: float | None,
    price: float,
    region: str | None,
    is_spot: bool,
    availability_status: str,
    available_gpu_count: int | None,
    observed_at: datetime,
    raw_ref: str | None,
) -> GpuOffer:
    billing_mode = "preemptible" if is_spot else "on_demand"
    return GpuOffer(
        provider="vultr",
        source_connector="vultr",
        source_offer_id=f"{plan_id}:{region or 'global'}:{billing_mode}",
        observed_at=observed_at,
        gpu_raw_name=gpu_name,
        gpu_model=gpu_model,
        gpu_count=gpu_count,
        vram_gb=vram_gb,
        price_usd_hr=price,
        available_gpu_count=available_gpu_count,
        country=None,
        region=region,
        is_spot=is_spot,
        is_secure=True,
        availability_status=availability_status,
        raw_ref=raw_ref,
        metadata={
            "plan_id": plan_id,
            "plan_type": plan.get("type"),
            "vcpu_count": plan.get("vcpu_count") or plan.get("cpu_count"),
            "ram_mb": plan.get("ram"),
            "disk_gb": plan.get("disk"),
            "deploy_ondemand": plan.get("deploy_ondemand"),
            "deploy_preemptible": plan.get("deploy_preemptible"),
            "price_basis": f"vultr_current_{billing_mode}_instance_hour",
            "capacity_basis": (
                "region_plan_deployability_lower_bound" if available_gpu_count else None
            ),
        },
    )


def _extract_gpu_plans(plans_payload: Any, metal_payload: Any) -> list[dict[str, Any]]:
    plans: list[dict[str, Any]] = []
    if isinstance(plans_payload, Mapping) and isinstance(
        plans_payload.get("plans"), list
    ):
        plans.extend(
            dict(row)
            for row in plans_payload["plans"]
            if isinstance(row, Mapping)
            and row.get("gpu_type")
            and row.get("type") != "vdm"
        )
    if isinstance(metal_payload, Mapping) and isinstance(
        metal_payload.get("plans_metal"), list
    ):
        plans.extend(
            dict(row)
            for row in metal_payload["plans_metal"]
            if isinstance(row, Mapping) and row.get("gpu_type")
        )
    return plans


def _extract_region_ids(payload: Any) -> list[str]:
    if not isinstance(payload, Mapping) or not isinstance(payload.get("regions"), list):
        return []
    return sorted(
        {
            str(row.get("id") or "").strip()
            for row in payload["regions"]
            if isinstance(row, Mapping) and str(row.get("id") or "").strip()
        }
    )


def _extract_available_plan_ids(payload: Any) -> list[str]:
    if not isinstance(payload, Mapping) or not isinstance(
        payload.get("available_plans"), list
    ):
        return []
    return [str(plan_id) for plan_id in payload["available_plans"] if plan_id]


def _gpu_name(plan: Mapping[str, Any]) -> str:
    return str(plan.get("gpu_type") or "").replace("_", " ").strip()


def _whole_gpu_count(value: Any) -> int | None:
    if isinstance(value, int):
        return value if value > 0 else None
    text = str(value or "").strip()
    if not text.isdigit():
        return None
    parsed = int(text)
    return parsed if parsed > 0 else None


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
