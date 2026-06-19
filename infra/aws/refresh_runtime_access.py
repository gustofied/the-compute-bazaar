"""Refresh laptop ingress rules for the dev AutoMQ/Windmill runtime security group."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
from datetime import UTC, datetime
from typing import Any
from urllib.request import urlopen

import boto3
from botocore.exceptions import ClientError


DEFAULT_REGION = "eu-west-3"
DEFAULT_SECURITY_GROUP_ID = "sg-0d5bcfecb6cd7ff50"
DEFAULT_PORTS = "22,8080"
MANAGED_DESCRIPTION_PREFIX = "Compute Bazaar laptop access"


def main() -> None:
    parser = argparse.ArgumentParser(prog="refresh_runtime_access.py")
    parser.add_argument(
        "--security-group-id",
        default=os.getenv("COMPUTE_BAZAAR_RUNTIME_SECURITY_GROUP_ID", DEFAULT_SECURITY_GROUP_ID),
        help="Security group that guards SSH/Windmill access to the dev runtime host.",
    )
    parser.add_argument("--region", default=os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or DEFAULT_REGION)
    parser.add_argument("--profile", default=os.getenv("AWS_PROFILE"))
    parser.add_argument("--ports", default=os.getenv("COMPUTE_BAZAAR_RUNTIME_ACCESS_PORTS", DEFAULT_PORTS))
    parser.add_argument("--ip-url", default="https://checkip.amazonaws.com")
    parser.add_argument(
        "--prune-stale",
        action="store_true",
        help="Remove old /32 rules previously created by this helper for the same ports.",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    ports = _parse_ports(args.ports)
    current_ip = _current_public_ip(args.ip_url)
    current_cidr = f"{current_ip}/32"
    session = (
        boto3.Session(profile_name=args.profile, region_name=args.region)
        if args.profile
        else boto3.Session(region_name=args.region)
    )
    ec2 = session.client("ec2")
    security_group = _describe_security_group(ec2, args.security_group_id)
    now = datetime.now(UTC).date().isoformat()
    description = f"{MANAGED_DESCRIPTION_PREFIX} {now}"

    changes: list[dict[str, Any]] = []
    for port in ports:
        existing = _ipv4_ranges_for_port(security_group, port)
        existing_cidrs = {row["cidr"] for row in existing}
        if current_cidr not in existing_cidrs:
            changes.append({"action": "authorize", "port": port, "cidr": current_cidr, "description": description})
            if not args.dry_run:
                _authorize(ec2, args.security_group_id, port, current_cidr, description)

        if args.prune_stale:
            for row in existing:
                if row["cidr"] == current_cidr:
                    continue
                if not row["cidr"].endswith("/32"):
                    continue
                if not str(row.get("description") or "").startswith(MANAGED_DESCRIPTION_PREFIX):
                    continue
                changes.append({"action": "revoke", "port": port, **row})
                if not args.dry_run:
                    _revoke(ec2, args.security_group_id, port, row["cidr"], row.get("description"))

    print(
        json.dumps(
            {
                "security_group_id": args.security_group_id,
                "region": args.region,
                "current_ip": current_ip,
                "current_cidr": current_cidr,
                "ports": ports,
                "dry_run": args.dry_run,
                "prune_stale": args.prune_stale,
                "changes": changes,
            },
            indent=2,
            sort_keys=True,
        )
    )


def _parse_ports(value: str) -> list[int]:
    ports = sorted({int(part.strip()) for part in value.split(",") if part.strip()})
    if not ports:
        raise SystemExit("At least one port is required")
    for port in ports:
        if port < 1 or port > 65535:
            raise SystemExit(f"Invalid TCP port: {port}")
    return ports


def _current_public_ip(url: str) -> str:
    with urlopen(url, timeout=10) as response:
        value = response.read().decode("utf-8").strip()
    address = ipaddress.ip_address(value)
    if address.version != 4:
        raise SystemExit("Only IPv4 /32 runtime access rules are supported")
    return str(address)


def _describe_security_group(ec2: Any, group_id: str) -> dict[str, Any]:
    response = ec2.describe_security_groups(GroupIds=[group_id])
    groups = response.get("SecurityGroups", [])
    if not groups:
        raise SystemExit(f"Security group not found: {group_id}")
    return dict(groups[0])


def _ipv4_ranges_for_port(security_group: dict[str, Any], port: int) -> list[dict[str, str | None]]:
    rows: list[dict[str, str | None]] = []
    for permission in security_group.get("IpPermissions", []):
        if permission.get("IpProtocol") != "tcp":
            continue
        if permission.get("FromPort") != port or permission.get("ToPort") != port:
            continue
        for ip_range in permission.get("IpRanges", []):
            cidr = ip_range.get("CidrIp")
            if cidr:
                rows.append({"cidr": str(cidr), "description": ip_range.get("Description")})
    return rows


def _authorize(ec2: Any, group_id: str, port: int, cidr: str, description: str) -> None:
    try:
        ec2.authorize_security_group_ingress(
            GroupId=group_id,
            IpPermissions=[
                {
                    "IpProtocol": "tcp",
                    "FromPort": port,
                    "ToPort": port,
                    "IpRanges": [{"CidrIp": cidr, "Description": description}],
                }
            ],
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "InvalidPermission.Duplicate":
            raise


def _revoke(ec2: Any, group_id: str, port: int, cidr: str, description: str | None) -> None:
    ip_range: dict[str, str] = {"CidrIp": cidr}
    if description:
        ip_range["Description"] = description
    ec2.revoke_security_group_ingress(
        GroupId=group_id,
        IpPermissions=[
            {
                "IpProtocol": "tcp",
                "FromPort": port,
                "ToPort": port,
                "IpRanges": [ip_range],
            }
        ],
    )


if __name__ == "__main__":
    main()
