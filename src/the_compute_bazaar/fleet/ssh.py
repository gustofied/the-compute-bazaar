"""Shared SSH command construction for Fleet operations."""

from __future__ import annotations

from pathlib import Path

from .models import FleetMachine


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
    if machine.ssh.identity_file:
        identity = Path(machine.ssh.identity_file).expanduser()
        known_hosts = (
            known_hosts_file
            or identity.parent / "compute_bazaar_fleet_known_hosts"
        )
        known_hosts.parent.mkdir(parents=True, exist_ok=True)
        command.extend(
            [
                "-i",
                str(identity),
                "-o",
                "ControlMaster=auto",
                "-o",
                "ControlPersist=60",
                "-o",
                f"ControlPath={known_hosts.parent / 'cbz-ssh-%C'}",
                "-o",
                "StrictHostKeyChecking=accept-new",
                "-o",
                f"UserKnownHostsFile={known_hosts}",
            ]
        )
    if machine.ssh.port:
        command.extend(["-p", str(machine.ssh.port)])
    return [*command, machine.ssh.target, remote_command]
