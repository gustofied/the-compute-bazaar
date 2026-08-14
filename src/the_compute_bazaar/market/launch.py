"""Launch one Sesterce market observation into Fleet."""

from __future__ import annotations

import re
import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from ..fleet import FleetMachine, FleetRegistry, SshEndpoint
from ..operations import OperationalLedger
from ..provisioning import Allocation, LaunchPlan, ProvisioningRequest
from .catalog import MarketCatalog
from .contracts import stable_id
from .lake import MarketLake
from .pipeline import MarketPipeline
from .sources.sesterce import SesterceSource


OBSERVATION_ID = re.compile(r"obs-[0-9a-f]{24}")


@dataclass(frozen=True)
class SesterceLaunchPlan:
    observation_id: str
    live_observation_id: str
    source_run_id: str
    observed_at: datetime
    source: str
    intermediary: str
    operator_id: str
    operator: str | None
    offer_id: str
    gpu_model: str | None
    gpu_count: int
    region: str
    ask_usd_hr: float
    total_usd_hr: float
    request: dict[str, Any]

    def payload(self) -> dict[str, Any]:
        row = asdict(self)
        row.pop("request")
        return {"rows": [row], "request": self.request, "submitted": False}


class SesterceLauncher:
    def __init__(
        self,
        *,
        lake_root: str,
        source: SesterceSource,
        registry: FleetRegistry | None = None,
        ledger: OperationalLedger | None = None,
    ) -> None:
        self.catalog = MarketCatalog.from_lake(lake_root)
        self.lake = MarketLake(lake_root)
        self.source = source
        self.registry = registry or FleetRegistry()
        self.ledger = ledger or OperationalLedger(
            self.registry.root / "operations.sqlite3",
            registry=self.registry,
        )

    def plan(
        self,
        observation_id: str,
        *,
        name: str,
        ssh_key_id: str,
        os_name: str | None = None,
    ) -> SesterceLaunchPlan:
        candidate = self._candidate(observation_id)
        read = self.source.read()
        if not read.complete:
            raise RuntimeError(read.error or "Sesterce offers are unavailable")
        source_run_id = (
            f"sesterce-live-{read.observed_at:%Y%m%dT%H%M%S}-"
            f"{stable_id(observation_id, time.time_ns(), length=8)}"
        )
        preflight = MarketPipeline(self.lake).record(
            self.source,
            read,
            source_run_id=source_run_id,
        )
        live = next(
            (
                offer
                for offer in preflight.offers
                if offer.operator_id == candidate["operator_id"]
                and offer.offer_id == candidate["offer_id"]
                and offer.region == candidate["region"]
                and offer.gpu_model == candidate["gpu_model"]
                and offer.gpu_count == candidate["gpu_count"]
            ),
            None,
        )
        if live is None or live.available is not True:
            raise RuntimeError("The selected Sesterce offer is no longer available")
        raw = _raw_offer(
            read.payload,
            operator_id=live.operator_id,
            offer_id=live.offer_id,
            region=live.region,
        )
        available_os = tuple(
            str(value)
            for value in _mapping(raw.get("configuration")).get("os", [])
            if value
        )
        selected_os = os_name or (available_os[0] if available_os else None)
        if not selected_os:
            raise ValueError("This offer has no VM image")
        if selected_os not in available_os:
            raise ValueError(f"VM image is not available: {selected_os}")
        total_usd_hr = round(live.ask_usd_hr * live.gpu_count, 6)
        return SesterceLaunchPlan(
            observation_id=observation_id,
            live_observation_id=live.observation_id,
            source_run_id=source_run_id,
            observed_at=read.observed_at,
            source=live.source,
            intermediary=live.intermediary,
            operator_id=live.operator_id or "",
            operator=live.operator,
            offer_id=live.offer_id,
            gpu_model=live.gpu_model,
            gpu_count=live.gpu_count,
            region=live.region,
            ask_usd_hr=live.ask_usd_hr,
            total_usd_hr=total_usd_hr,
            request={
                "name": name,
                "cloudProvider": live.operator_id,
                "instanceId": live.offer_id,
                "region": live.region,
                "vm": {"os": selected_os},
                "sshKeyId": ssh_key_id,
            },
        )

    def launch(
        self,
        observation_id: str,
        *,
        name: str,
        ssh_key_id: str,
        max_hourly_usd: float,
        confirm: bool,
        os_name: str | None = None,
        wait_seconds: int = 180,
        runtime_minutes: int = 30,
    ) -> tuple[SesterceLaunchPlan, FleetMachine]:
        plan = self.plan(
            observation_id,
            name=name,
            ssh_key_id=ssh_key_id,
            os_name=os_name,
        )
        if plan.total_usd_hr > max_hourly_usd:
            raise ValueError(
                f"Current price ${plan.total_usd_hr:g}/hr exceeds "
                f"${max_hourly_usd:g}/hr"
            )
        if not confirm:
            raise ValueError("Use --confirm to create this paid instance")
        request = ProvisioningRequest.from_plan(
            self._provisioning_plan(plan),
            runtime_minutes=runtime_minutes,
            max_hourly_usd=max_hourly_usd,
        )
        attempt = self.ledger.begin_provisioning(request)
        try:
            instance = self.source.create_instance(plan.request)
            resource_id = _required(instance, "_id")
        except Exception as exc:
            self.ledger.complete_provisioning_attempt(
                attempt.attempt_id,
                state="uncertain",
                error=str(exc),
            )
            raise
        created_at = _datetime(instance.get("createdAt")) or datetime.now(UTC)
        allocation = Allocation(
            allocation_id="allocation-"
            + stable_id(request.request_id, resource_id, length=16),
            request_id=request.request_id,
            successful_attempt_id=attempt.attempt_id,
            candidate_observation_id=plan.observation_id,
            preflight_observation_id=plan.live_observation_id,
            source=plan.source,
            intermediary=plan.intermediary,
            operator=plan.operator,
            offer_id=plan.offer_id,
            source_resource_id=resource_id,
            state=_instance_state(instance),
            price_usd_gpu_hr=plan.ask_usd_hr,
            price_usd_instance_hr=plan.total_usd_hr,
            created_at=created_at,
            terminate_at=request.created_at + timedelta(minutes=runtime_minutes),
            updated_at=datetime.now(UTC),
        )
        self.ledger.complete_allocation(attempt.attempt_id, allocation)
        machine = self._machine(plan, instance, allocation_id=allocation.allocation_id)
        self.registry.put(machine)
        deadline = time.monotonic() + max(0, wait_seconds)
        while machine.state == "provisioning" and time.monotonic() < deadline:
            time.sleep(5)
            instance = self.source.get_instance(_required(instance, "_id"))
            machine = self._machine(
                plan,
                instance,
                allocation_id=allocation.allocation_id,
            )
            self.registry.put(machine)
            self.ledger.record_machine_state(machine)
        return plan, machine

    def terminate(self, host_id: str, *, confirm: bool) -> FleetMachine:
        machine = self.registry.get(host_id)
        allocation = self.ledger.allocation_for_machine(machine)
        if allocation["source"] != "sesterce":
            raise ValueError("This is not a Sesterce Fleet host")
        if not confirm:
            raise ValueError("Use --confirm to delete this Sesterce instance")
        self.source.delete_instance(str(allocation["source_resource_id"]))
        terminated = machine.model_copy(update={"state": "terminated", "ssh": None})
        self.registry.put(terminated)
        terminated_at = datetime.now(UTC)
        self.ledger.record_machine_state(terminated, occurred_at=terminated_at)
        self.ledger.stop_host_workloads(
            host_id,
            reason="Fleet host terminated",
            ended_at=terminated_at,
        )
        return terminated

    def refresh(self, host_id: str) -> FleetMachine:
        machine = self.registry.get(host_id)
        allocation = self.ledger.allocation_for_machine(machine)
        if allocation["source"] != "sesterce":
            raise ValueError("This is not a Sesterce Fleet host")
        instance = self.source.get_instance(str(allocation["source_resource_id"]))
        refreshed = machine.model_copy(
            update={
                "state": _instance_state(instance),
                "ssh": _instance_ssh(instance),
            }
        )
        self.registry.put(refreshed)
        self.ledger.record_machine_state(refreshed)
        return refreshed

    def _provisioning_plan(self, plan: SesterceLaunchPlan) -> LaunchPlan:
        return LaunchPlan(
            plan_id="plan-"
            + stable_id(
                plan.observation_id,
                plan.live_observation_id,
                plan.request["name"],
                length=16,
            ),
            offer_id=plan.offer_id,
            candidate_observation_id=plan.observation_id,
            preflight_observation_id=plan.live_observation_id,
            preflight_batch_id=plan.source_run_id,
            market_product_key=(
                f"{plan.source}:{plan.operator_id}:{plan.offer_id}:{plan.region}"
            ),
            source_connector=plan.source,
            capacity_provider=plan.operator or plan.operator_id,
            operation="create_instance",
            endpoint=self.source.instances_endpoint,
            observed_at=plan.observed_at,
            gpu_model=plan.gpu_model or "unknown",
            gpu_count=plan.gpu_count,
            price_usd_gpu_hr=plan.ask_usd_hr,
            price_usd_instance_hr=plan.total_usd_hr,
            cloud_type="vm",
            location=plan.region,
            status="ready_for_confirmation",
            credentials_configured=True,
            request=plan.request,
        )

    def _candidate(self, observation_id: str) -> dict[str, Any]:
        if not OBSERVATION_ID.fullmatch(observation_id):
            raise ValueError("Expected a Silver observation_id")
        rows = self.catalog.rows(
            "select * from silver.gpu_offers "
            f"where observation_id = '{observation_id}' limit 2"
        )
        if len(rows) != 1:
            raise KeyError(f"Unknown market observation: {observation_id}")
        candidate = rows[0]
        if candidate.get("source") != "sesterce":
            raise ValueError("Only Sesterce observations can be launched")
        if not candidate.get("operator_id"):
            raise ValueError("This observation has no Sesterce operator ID")
        return candidate

    @staticmethod
    def _machine(
        plan: SesterceLaunchPlan,
        instance: Mapping[str, Any],
        *,
        allocation_id: str,
    ) -> FleetMachine:
        resource_id = _required(instance, "_id")
        return FleetMachine(
            host_id=f"sesterce:{resource_id}",
            allocation_id=allocation_id,
            name=str(instance.get("name") or plan.request["name"]),
            state=_instance_state(instance),
            expected_gpu_model=plan.gpu_model,
            expected_gpu_count=plan.gpu_count,
            created_at=_datetime(instance.get("createdAt")) or datetime.now(UTC),
            ssh=_instance_ssh(instance),
        )


def _raw_offer(
    payload: Any,
    *,
    operator_id: str | None,
    offer_id: str,
    region: str,
) -> Mapping[str, Any]:
    for value in payload if isinstance(payload, list) else []:
        if not isinstance(value, Mapping):
            continue
        cloud = _mapping(value.get("cloud"))
        locations = value.get("availability")
        if (
            str(cloud.get("_id") or "") == str(operator_id or "")
            and str(value.get("instanceId") or "") == offer_id
            and any(
                isinstance(item, Mapping)
                and item.get("region") == region
                and item.get("available") is True
                for item in (locations if isinstance(locations, list) else [])
            )
        ):
            return value
    raise RuntimeError("The selected Sesterce offer is no longer available")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _required(value: Mapping[str, Any], key: str) -> str:
    result = str(value.get(key) or "").strip()
    if not result:
        raise RuntimeError(f"Sesterce response has no {key}")
    return result


def _integer(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _instance_state(instance: Mapping[str, Any]) -> str:
    return {
        "pending": "provisioning",
        "active": "running",
        "deleted": "terminated",
        "deleting": "terminated",
    }.get(str(instance.get("status") or "unknown").lower(), "unknown")


def _instance_ssh(instance: Mapping[str, Any]) -> SshEndpoint | None:
    ip = str(instance.get("ip") or "").strip()
    user = str(instance.get("sshUser") or "").strip()
    port = _integer(instance.get("sshPort"))
    return SshEndpoint(target=f"{user}@{ip}", port=port) if ip and user else None


def _datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
