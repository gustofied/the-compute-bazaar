"""Small standard-library client used by Windmill bootstrap scripts."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "http://127.0.0.1:8081"
DEFAULT_WORKSPACE = "compute-bazaar"
DEFAULT_FOLDER = "compute-bazaar"
DEFAULT_CRON = "0 0 * * * *"
WAIT_RESULT_TIMEOUT_SECONDS = 900


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

    def upsert_variable(
        self, *, path: str, value: str, is_secret: bool, description: str
    ) -> None:
        body = {
            "path": path,
            "value": value,
            "is_secret": is_secret,
            "description": description,
        }
        try:
            self._post(
                f"/w/{self.workspace}/variables/create",
                body,
                ok_statuses={200, 201},
            )
        except HTTPError as exc:
            if exc.code not in {400, 409}:
                raise
            self._post(
                f"/w/{self.workspace}/variables/update/{quote(path, safe='')}",
                body,
                ok_statuses={200, 201},
            )

    def upsert_script(
        self, *, path: str, content: str, summary: str, description: str
    ) -> None:
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
        self._post(
            f"/w/{self.workspace}/scripts/create", body, ok_statuses={200, 201}
        )

    def get_script_hash(self, path: str) -> str | None:
        try:
            payload = self._get(
                f"/w/{self.workspace}/scripts/get/p/{path}", ok_statuses={200}
            )
        except HTTPError as exc:
            if exc.code == 404:
                return None
            raise
        return str(json.loads(payload.decode("utf-8"))["hash"])

    def run_script(self, path: str, args: dict[str, Any]) -> str:
        payload = self._post(
            f"/w/{self.workspace}/jobs/run/p/{path}", args, ok_statuses={201}
        )
        return payload.decode("utf-8").strip().strip('"')

    def run_script_wait_result(self, path: str, args: dict[str, Any]) -> Any:
        payload = self._post(
            f"/w/{self.workspace}/jobs/run_wait_result/p/{path}",
            args,
            ok_statuses={200},
            timeout=WAIT_RESULT_TIMEOUT_SECONDS,
        )
        return json.loads(payload.decode("utf-8"))

    def delete_schedule(self, path: str) -> None:
        self._delete(
            f"/w/{self.workspace}/schedules/delete/{quote(path, safe='')}",
            ok_statuses={200, 404},
        )

    def delete_script(self, path: str) -> None:
        self._post(
            f"/w/{self.workspace}/scripts/delete/p/{quote(path, safe='')}",
            {},
            ok_statuses={200, 404},
        )

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
            self._post(
                f"/w/{self.workspace}/schedules/create",
                body,
                ok_statuses={200, 201},
            )
        except HTTPError as exc:
            if exc.code not in {400, 409}:
                raise
            self._post(
                f"/w/{self.workspace}/schedules/update/{quote(path, safe='')}",
                body,
                ok_statuses={200, 201},
            )
        self._post(
            f"/w/{self.workspace}/schedules/setenabled/{quote(path, safe='')}",
            {"enabled": enabled},
            ok_statuses={200},
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
                    raise RuntimeError(
                        f"Unexpected status {response.status} for {path}: {payload!r}"
                    )
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
                    raise RuntimeError(
                        f"Unexpected status {response.status} for {path}: {payload!r}"
                    )
                return payload
        except HTTPError as exc:
            if exc.code in ok_statuses:
                return exc.read()
            raise

    def _delete(self, path: str, *, ok_statuses: set[int]) -> bytes:
        request = Request(
            f"{self.base_url}/api{path}",
            headers={"Authorization": f"Bearer {self.token}"},
            method="DELETE",
        )
        try:
            with urlopen(request, timeout=20) as response:
                payload = response.read()
                if response.status not in ok_statuses:
                    raise RuntimeError(
                        f"Unexpected status {response.status} for {path}: {payload!r}"
                    )
                return payload
        except HTTPError as exc:
            if exc.code in ok_statuses:
                return exc.read()
            raise


def load_local_env(path: str = ".env") -> None:
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


def read_token_file(path: str = ".secrets/windmill-bootstrap-token.txt") -> str | None:
    token_path = Path(path)
    if not token_path.exists():
        return None
    token = token_path.read_text(encoding="utf-8").strip()
    return token or None
