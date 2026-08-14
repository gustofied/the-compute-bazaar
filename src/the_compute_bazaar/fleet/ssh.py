"""Shared SSH command construction for Fleet operations."""

from __future__ import annotations

import os
from pathlib import Path

from .models import FleetMachine
from .registry import default_fleet_root


def ssh_command(
    machine: FleetMachine,
    *,
    remote_command: str,
    known_hosts_file: Path | None = None,
) -> list[str]:
    if machine.ssh is None:
        raise ValueError(f"Fleet host {machine.host_id} has no SSH endpoint")
    command = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=15",
    ]
    known_hosts = known_hosts_file or default_fleet_root() / "known_hosts"
    known_hosts.parent.mkdir(parents=True, exist_ok=True)
    control_root = Path("/tmp") / f"compute-bazaar-{os.getuid()}"
    control_root.mkdir(mode=0o700, exist_ok=True)
    control_root.chmod(0o700)
    command.extend(
        [
            "-o",
            "ControlMaster=auto",
            "-o",
            "ControlPersist=60",
            "-o",
            f"ControlPath={control_root / 'ssh-%C'}",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            f"UserKnownHostsFile={known_hosts}",
        ]
    )
    if machine.ssh.identity_file:
        identity = Path(machine.ssh.identity_file).expanduser()
        command.extend(["-i", str(identity)])
    if machine.ssh.port:
        command.extend(["-p", str(machine.ssh.port)])
    return [*command, machine.ssh.target, remote_command]
