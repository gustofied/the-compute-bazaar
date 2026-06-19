"""Bootstrap Windmill provider ingestion jobs.

Creates or updates the Windmill folder, variables, script body, and hourly schedule
for Vast or Lium ingestion.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "http://127.0.0.1:8081"
DEFAULT_WORKSPACE = "compute-bazaar"
DEFAULT_FOLDER = "compute-bazaar"
DEFAULT_CRON = "0 0 * * * *"


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    api_key_env: str
    api_key_variable: str
    script_file: str
    summary: str
    description: str
    extra_args: dict[str, Any]


PROVIDERS = {
    "vast": ProviderConfig(
        name="vast",
        api_key_env="VAST_API_KEY",
        api_key_variable="vast_api_key",
        script_file="vast_hourly.py",
        summary="Hourly Vast GPU price ingestion",
        description="Fetches Vast offers, writes raw/S3 Parquet data, and publishes AutoMQ events.",
        extra_args={},
    ),
    "lium": ProviderConfig(
        name="lium",
        api_key_env="LIUM_API_KEY",
        api_key_variable="lium_api_key",
        script_file="lium_hourly.py",
        summary="Hourly Lium GPU price ingestion",
        description="Fetches Lium executors, writes raw/S3 Parquet data, and publishes AutoMQ events.",
        extra_args={"size": 200, "paginate": True, "max_pages": 10},
    ),
}


def main() -> None:
    _load_local_env()

    parser = argparse.ArgumentParser(description="Create or update Windmill provider ingestion jobs")
    parser.add_argument("--provider", choices=sorted(PROVIDERS), required=True)
    parser.add_argument("--base-url", default=os.getenv("WINDMILL_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--workspace", default=os.getenv("WINDMILL_WORKSPACE", DEFAULT_WORKSPACE))
    parser.add_argument("--folder", default=os.getenv("WINDMILL_FOLDER", DEFAULT_FOLDER))
    parser.add_argument("--token", default=os.getenv("WINDMILL_TOKEN") or _read_token_file())
    parser.add_argument("--timezone", default=os.getenv("WINDMILL_TIMEZONE", "UTC"))
    parser.add_argument("--cron", default=os.getenv("WINDMILL_CRON", DEFAULT_CRON))
    parser.add_argument("--disabled", action="store_true", help="Create the schedule disabled")
    parser.add_argument("--run-now", action="store_true", help="Run the provider script once after upsert")
    parser.add_argument("--run-id", help="Optional run_id to pass to the one-off run")
    parser.add_argument("--wait", action="store_true", help="Wait for the one-off run and include its result")
    args = parser.parse_args()

    if not args.token:
        raise SystemExit("Set WINDMILL_TOKEN, pass --token, or create .secrets/windmill-bootstrap-token.txt")

    provider = PROVIDERS[args.provider]
    client = WindmillClient(base_url=args.base_url, workspace=args.workspace, token=args.token)
    folder = args.folder

    client.create_folder(folder)
    for variable in required_variables(folder, provider):
        client.upsert_variable(**variable)

    script_path = f"f/{folder}/{provider.name}_hourly"
    schedule_path = f"f/{folder}/{provider.name}_hourly_hourly"
    script_body = Path(__file__).with_name(provider.script_file).read_text(encoding="utf-8")

    client.upsert_script(
        path=script_path,
        content=script_body,
        summary=provider.summary,
        description=provider.description,
    )
    run_args = schedule_args(folder, provider)
    client.upsert_schedule(
        path=schedule_path,
        script_path=script_path,
        schedule=args.cron,
        timezone=args.timezone,
        enabled=not args.disabled,
        summary=provider.summary,
        description=provider.description,
        args=run_args,
    )

    job_id = None
    job_result = None
    if args.run_now:
        one_off_args = dict(run_args)
        if args.run_id:
            one_off_args["run_id"] = args.run_id
        if args.wait:
            job_result = client.run_script_wait_result(script_path, one_off_args)
        else:
            job_id = client.run_script(script_path, one_off_args)

    print(
        json.dumps(
            {
                "workspace": args.workspace,
                "provider": provider.name,
                "script_path": script_path,
                "schedule_path": schedule_path,
                "schedule": args.cron,
                "enabled": not args.disabled,
                "job_id": job_id,
                "job_result": job_result,
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
            ok_statuses={200, 201, 400, 409},
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

    def run_script(self, path: str, args: dict[str, Any]) -> str:
        payload = self._post(f"/w/{self.workspace}/jobs/run/p/{path}", args, ok_statuses={201})
        return payload.decode("utf-8").strip().strip('"')

    def run_script_wait_result(self, path: str, args: dict[str, Any]) -> Any:
        # Windmill keeps the HTTP request open while the worker runs the script.
        payload = self._post(
            f"/w/{self.workspace}/jobs/run_wait_result/p/{path}",
            args,
            ok_statuses={200},
            timeout=300,
        )
        return json.loads(payload.decode("utf-8"))

    def upsert_schedule(
        self,
        *,
        path: str,
        script_path: str,
        schedule: str,
        timezone: str,
        enabled: bool,
        summary: str,
        description: str,
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
            "summary": summary,
            "description": description,
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

    def _post(
        self,
        path: str,
        body: dict[str, Any],
        *,
        ok_statuses: set[int],
        timeout: int = 20,
    ) -> bytes:
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
            with urlopen(request, timeout=timeout) as response:
                payload = response.read()
                if response.status not in ok_statuses:
                    raise RuntimeError(f"Unexpected status {response.status} for {path}: {payload!r}")
                return payload
        except HTTPError as exc:
            if exc.code in ok_statuses:
                return exc.read()
            raise


def required_variables(folder: str, provider: ProviderConfig) -> list[dict[str, Any]]:
    env_to_variable = [
        (provider.api_key_env, provider.api_key_variable, True, f"{provider.name.title()} API key"),
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


def schedule_args(folder: str, provider: ProviderConfig) -> dict[str, Any]:
    args = {
        "api_key": f"$var:f/{folder}/{provider.api_key_variable}",
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
    args.update(provider.extra_args)
    return args


def _load_local_env(path: str = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _read_token_file(path: str = ".secrets/windmill-bootstrap-token.txt") -> str | None:
    token_path = Path(path)
    if not token_path.exists():
        return None
    token = token_path.read_text(encoding="utf-8").strip()
    return token or None


if __name__ == "__main__":
    try:
        main()
    except HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        print(f"Windmill API error {error.code}: {body}", file=sys.stderr)
        raise SystemExit(1) from error
