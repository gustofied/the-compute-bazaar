"""Launch one Sesterce market observation into Fleet."""

from __future__ import annotations

import re
import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from ..fleet import FleetMachine, FleetRegistry, SshEndpoint
from .catalog import MarketCatalog
from .sources.sesterce import SesterceSource


OBSERVATION_ID = re.compile(r"obs-[0-9a-f]{24}")


@dataclass(frozen=True)
class SesterceLaunchPlan:
    observation_id: str
    live_observation_id: str
    observed_at: datetime
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
    ) -> None:
        self.catalog = MarketCatalog.from_lake(lake_root)
        self.source = source
        self.registry = registry or FleetRegistry()

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
        source_run_id = f"sesterce-live-{read.observed_at:%Y%m%dT%H%M%S}"
        normalized = self.source.normalize(read, source_run_id=source_run_id)
        live = next(
            (
                offer
                for offer in normalized.offers
                if offer.operator_id == candidate["operator_id"]
                and offer.offer_id == candidate["offer_id"]
                and offer.region == candidate["region"]
            ),
            None,
        )
        if live is None or not live.available:
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
            observed_at=read.observed_at,
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
        instance = self.source.create_instance(plan.request)
        machine = self._machine(plan, instance)
        self.registry.put(machine)
        deadline = time.monotonic() + max(0, wait_seconds)
        while machine.state == "provisioning" and time.monotonic() < deadline:
            time.sleep(5)
            instance = self.source.get_instance(_required(instance, "_id"))
            machine = self._machine(plan, instance)
            self.registry.put(machine)
        return plan, machine

    def terminate(self, host_id: str, *, confirm: bool) -> FleetMachine:
        machine = self.registry.get(host_id)
        if machine.source != "sesterce" or not machine.provider_resource_id:
            raise ValueError("This is not a Sesterce Fleet host")
        if not confirm:
            raise ValueError("Use --confirm to delete this Sesterce instance")
        self.source.delete_instance(machine.provider_resource_id)
        terminated = machine.model_copy(update={"state": "terminated", "ssh": None})
        return self.registry.put(terminated)

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
    ) -> FleetMachine:
        resource_id = _required(instance, "_id")
        status = str(instance.get("status") or "unknown").lower()
        state = {
            "pending": "provisioning",
            "active": "running",
            "deleted": "terminated",
            "deleting": "terminated",
        }.get(status, "unknown")
        ip = str(instance.get("ip") or "").strip()
        user = str(instance.get("sshUser") or "").strip()
        port = _integer(instance.get("sshPort"))
        ssh = SshEndpoint(target=f"{user}@{ip}", port=port) if ip and user else None
        return FleetMachine(
            host_id=f"sesterce:{resource_id}",
            source="sesterce",
            source_offer_id=plan.offer_id,
            provider_resource_id=resource_id,
            ask_usd_hr=plan.ask_usd_hr,
            name=str(instance.get("name") or plan.request["name"]),
            state=state,
            expected_gpu_model=plan.gpu_model,
            expected_gpu_count=plan.gpu_count,
            created_at=_datetime(instance.get("createdAt")) or datetime.now(UTC),
            ssh=ssh,
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


def _datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
