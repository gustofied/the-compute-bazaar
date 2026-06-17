"""Bootstrap the Windmill Vast hourly ingestion job.

Run this after completing the first Windmill login and creating an API token.
It uses only the standard library so it can run from a normal shell.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "http://127.0.0.1:8081"
DEFAULT_WORKSPACE = "compute-bazaar"
DEFAULT_FOLDER = "compute-bazaar"
DEFAULT_CRON = "0 0 * * * *"


def main() -> None:
    parser = argparse.ArgumentParser(description="Create the Windmill Vast hourly ingestion job")
    parser.add_argument("--base-url", default=os.getenv("WINDMILL_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--workspace", default=os.getenv("WINDMILL_WORKSPACE", DEFAULT_WORKSPACE))
    parser.add_argument("--folder", default=os.getenv("WINDMILL_FOLDER", DEFAULT_FOLDER))
    parser.add_argument("--token", default=os.getenv("WINDMILL_TOKEN"))
    parser.add_argument("--timezone", default=os.getenv("WINDMILL_TIMEZONE", "UTC"))
    parser.add_argument("--cron", default=os.getenv("WINDMILL_CRON", DEFAULT_CRON))
    parser.add_argument("--disabled", action="store_true", help="Create the schedule disabled")
    args = parser.parse_args()

    if not args.token:
        raise SystemExit("Set WINDMILL_TOKEN or pass --token")

    client = WindmillClient(base_url=args.base_url, workspace=args.workspace, token=args.token)
    folder = args.folder

    client.create_folder(folder)
    for variable in required_variables(folder):
        client.upsert_variable(**variable)

    script_path = f"f/{folder}/vast_hourly"
    schedule_path = f"f/{folder}/vast_hourly_hourly"
    script_body = Path(__file__).with_name("vast_hourly.py").read_text(encoding="utf-8")

    client.upsert_script(
        path=script_path,
        content=script_body,
        summary="Hourly Vast GPU price ingestion",
        description="Fetches Vast offers, writes raw/S3 Parquet data, and publishes AutoMQ events.",
    )
    client.upsert_schedule(
        path=schedule_path,
        script_path=script_path,
        schedule=args.cron,
        timezone=args.timezone,
        enabled=not args.disabled,
        args=schedule_args(folder),
    )

    print(
        json.dumps(
            {
                "workspace": args.workspace,
                "script_path": script_path,
                "schedule_path": schedule_path,
                "schedule": args.cron,
                "enabled": not args.disabled,
            },
            indent=2,
            sort_keys=True,
        )
    )


class WindmillClient:
    def __init__(self, *, base_url: str, workspace: str, token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.workspace = workspace
        self.token = token

    def create_folder(self, name: str) -> None:
        self._post(
            f"/w/{self.workspace}/folders/create",
            {"name": name, "summary": "Compute Bazaar ingestion jobs"},
            ok_statuses={200, 201, 409},
        )

    def upsert_variable(self, *, path: str, value: str, is_secret: bool, description: str) -> None:
        body = {
            "path": path,
            "value": value,
            "is_secret": is_secret,
            "description": description,
        }
        try:
            self._post(f"/w/{self.workspace}/variables/create", body, ok_statuses={200, 201})
        except HTTPError as exc:
            if exc.code not in {400, 409}:
                raise
            self._post(
                f"/w/{self.workspace}/variables/update/{quote(path, safe='')}",
                body,
                ok_statuses={200, 201},
            )

    def upsert_script(self, *, path: str, content: str, summary: str, description: str) -> None:
        parent_hash = self.get_script_hash(path)
        body = {
            "path": path,
            "summary": summary,
            "description": description,
            "content": content,
            "language": "python3",
            "kind": "script",
        }
        if parent_hash:
            body["parent_hash"] = parent_hash
        self._post(f"/w/{self.workspace}/scripts/create", body, ok_statuses={200, 201})

    def get_script_hash(self, path: str) -> str | None:
        try:
            payload = self._get(f"/w/{self.workspace}/scripts/get/p/{path}", ok_statuses={200})
        except HTTPError as exc:
            if exc.code == 404:
                return None
            raise
        return str(json.loads(payload.decode("utf-8"))["hash"])

    def upsert_schedule(
        self,
        *,
        path: str,
        script_path: str,
        schedule: str,
        timezone: str,
        enabled: bool,
        args: dict[str, Any],
    ) -> None:
        body = {
            "path": path,
            "schedule": schedule,
            "timezone": timezone,
            "script_path": script_path,
            "is_flow": False,
            "args": args,
            "enabled": enabled,
            "summary": "Hourly Vast GPU price ingestion",
            "description": "Fetch Vast offers and publish normalized market events.",
            "no_flow_overlap": True,
        }
        try:
            self._post(f"/w/{self.workspace}/schedules/create", body, ok_statuses={200, 201})
        except HTTPError as exc:
            if exc.code not in {400, 409}:
                raise
            self._post(
                f"/w/{self.workspace}/schedules/update/{quote(path, safe='')}",
                body,
                ok_statuses={200, 201},
            )

    def _get(self, path: str, *, ok_statuses: set[int]) -> bytes:
        request = Request(
            f"{self.base_url}/api{path}",
            headers={"Authorization": f"Bearer {self.token}"},
            method="GET",
        )
        try:
            with urlopen(request, timeout=20) as response:
                payload = response.read()
                if response.status not in ok_statuses:
                    raise RuntimeError(f"Unexpected status {response.status} for {path}: {payload!r}")
                return payload
        except HTTPError as exc:
            if exc.code in ok_statuses:
                return exc.read()
            raise

    def _post(self, path: str, body: dict[str, Any], *, ok_statuses: set[int]) -> bytes:
        request = Request(
            f"{self.base_url}/api{path}",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=20) as response:
                payload = response.read()
                if response.status not in ok_statuses:
                    raise RuntimeError(f"Unexpected status {response.status} for {path}: {payload!r}")
                return payload
        except HTTPError as exc:
            if exc.code in ok_statuses:
                return exc.read()
            raise


def required_variables(folder: str) -> list[dict[str, Any]]:
    env_to_variable = [
        ("VAST_API_KEY", "vast_api_key", True, "Vast API key"),
        ("COMPUTE_BAZAAR_RAW_ROOT", "raw_root", False, "Raw S3 root"),
        ("COMPUTE_BAZAAR_LAKE_ROOT", "lake_root", False, "Lake S3 root"),
        ("COMPUTE_BAZAAR_KAFKA_BOOTSTRAP_SERVERS", "kafka_bootstrap_servers", False, "Kafka bootstrap servers"),
        ("COMPUTE_BAZAAR_KAFKA_USERNAME", "kafka_username", True, "Kafka SASL username"),
        ("COMPUTE_BAZAAR_KAFKA_PASSWORD", "kafka_password", True, "Kafka SASL password"),
    ]
    variables: list[dict[str, Any]] = []
    missing: list[str] = []
    for env_name, variable_name, is_secret, description in env_to_variable:
        value = os.getenv(env_name)
        if value is None:
            missing.append(env_name)
            continue
        variables.append(
            {
                "path": f"f/{folder}/{variable_name}",
                "value": value,
                "is_secret": is_secret,
                "description": description,
            }
        )
    if missing:
        raise SystemExit(f"Missing required environment variables: {', '.join(missing)}")
    return variables


def schedule_args(folder: str) -> dict[str, Any]:
    return {
        "api_key": f"$var:f/{folder}/vast_api_key",
        "raw_root": f"$var:f/{folder}/raw_root",
        "lake_root": f"$var:f/{folder}/lake_root",
        "automq_bootstrap_servers": f"$var:f/{folder}/kafka_bootstrap_servers",
        "kafka_security_protocol": "SASL_PLAINTEXT",
        "kafka_sasl_mechanism": "SCRAM-SHA-256",
        "kafka_username": f"$var:f/{folder}/kafka_username",
        "kafka_password": f"$var:f/{folder}/kafka_password",
        "aws_region": os.getenv("AWS_REGION", "eu-west-3"),
        "topic_prefix": "gpu",
        "dry_run": False,
    }


if __name__ == "__main__":
    try:
        main()
    except HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        print(f"Windmill API error {error.code}: {body}", file=sys.stderr)
        raise SystemExit(1) from error
