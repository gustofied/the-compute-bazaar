"""Private local registry for provisioned compute."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .models import FleetMachine


def default_fleet_root() -> Path:
    configured = os.getenv("COMPUTE_BAZAAR_FLEET_HOME")
    if configured:
        return Path(configured).expanduser()
    state_home = Path(os.getenv("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return state_home / "compute-bazaar" / "fleet"


class FleetRegistry:
    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or default_fleet_root()).expanduser().resolve()
        self.path = self.root / "hosts.json"

    def list(self) -> list[FleetMachine]:
        return sorted(
            self._machines().values(),
            key=lambda machine: (machine.created_at, machine.host_id),
            reverse=True,
        )

    def get(self, host_id: str) -> FleetMachine:
        try:
            return self._machines()[host_id]
        except KeyError as exc:
            raise KeyError(f"Unknown Fleet host: {host_id}") from exc

    def put(self, machine: FleetMachine) -> FleetMachine:
        machines = self._machines()
        machines[machine.host_id] = machine
        self._write(machines)
        return machine

    def _machines(self) -> dict[str, FleetMachine]:
        if not self.path.is_file():
            return {}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if payload.get("contract") != "compute-bazaar.fleet-registry.v1":
            raise ValueError(f"Unsupported Fleet registry: {self.path}")
        rows = payload.get("machines")
        if not isinstance(rows, list):
            raise ValueError(f"Invalid Fleet registry: {self.path}")
        return {
            machine.host_id: machine
            for row in rows
            if isinstance(row, dict)
            for machine in [FleetMachine.model_validate(row)]
        }

    def _write(self, machines: dict[str, FleetMachine]) -> None:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        payload: dict[str, Any] = {
            "contract": "compute-bazaar.fleet-registry.v1",
            "machines": [
                machine.model_dump(mode="json")
                for machine in sorted(machines.values(), key=lambda item: item.host_id)
            ],
        }
        handle, temporary = tempfile.mkstemp(
            dir=self.root, prefix="hosts-", suffix=".json"
        )
        temporary_path = Path(temporary)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, indent=2, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            temporary_path.chmod(0o600)
            temporary_path.replace(self.path)
        finally:
            temporary_path.unlink(missing_ok=True)
