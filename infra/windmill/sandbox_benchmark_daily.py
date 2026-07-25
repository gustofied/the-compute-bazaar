"""Windmill script for daily sandbox benchmark source ingestion and dispatch."""

from __future__ import annotations

import json
import os
import subprocess
from urllib.error import HTTPError
from urllib.request import Request, urlopen


DEFAULT_PROVIDERS = (
    "e2b,daytona-vm,blaxel,modal-gvisor,modal-vm,novita"
)


def main(
    source_repository: str = "starslingdev/hpc-sandbox-benchmarks",
    source_ref: str = "main",
    lake_root: str | None = None,
    dispatch_repository: str | None = None,
    github_token: str | None = None,
    dispatch: bool = False,
    workflow_id: str = "bench-matrix.yml",
    workflow_ref: str = "main",
    providers: str = DEFAULT_PROVIDERS,
    suites: str = "realworld",
    replicas: str = "12",
    pts_passes: str = "",
) -> dict[str, object]:
    """Ingest the latest trusted dataset, then optionally start tomorrow's run."""
    output_root = _sandbox_output_root(lake_root)
    command = [
        "/opt/compute-bazaar/.venv/bin/sandbox-cost",
        "refresh-benchmark",
        "--output-root",
        output_root,
        "--source-repository",
        source_repository,
        "--source-ref",
        source_ref,
        "--publish-operational",
    ]
    env = os.environ.copy()
    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    source_refresh = json.loads(completed.stdout)

    dispatch_result: dict[str, object] = {
        "requested": False,
        "reason": "dispatch_disabled",
    }
    if dispatch:
        if not dispatch_repository:
            raise ValueError(
                "dispatch_repository is required when dispatch is enabled"
            )
        if not github_token:
            raise ValueError("github_token is required when dispatch is enabled")
        dispatch_result = _dispatch_benchmark(
            repository=dispatch_repository,
            workflow_id=workflow_id,
            ref=workflow_ref,
            token=github_token,
            providers=providers,
            suites=suites,
            replicas=replicas,
            pts_passes=pts_passes,
        )

    return {
        "output_root": output_root,
        "source_repository": source_repository,
        "source_refresh": source_refresh,
        "dispatch": dispatch_result,
        "gold_pickup": (
            "The next hourly market run reads the operational workload "
            "manifest and rebuilds sandbox gold/public JSON."
        ),
    }


def _dispatch_benchmark(
    *,
    repository: str,
    workflow_id: str,
    ref: str,
    token: str,
    providers: str,
    suites: str,
    replicas: str,
    pts_passes: str,
) -> dict[str, object]:
    repository = _repository_slug(repository)
    try:
        replica_count = int(replicas)
    except ValueError as exc:
        raise ValueError("replicas must be a positive integer") from exc
    if replica_count < 1:
        raise ValueError("replicas must be a positive integer")
    payload = json.dumps(
        {
            "ref": ref,
            "inputs": {
                "providers": providers,
                "suites": suites,
                "replicas": str(replica_count),
                "pts_passes": pts_passes,
                "allow_branch": False,
            },
        }
    ).encode("utf-8")
    request = Request(
        (
            "https://api.github.com/repos/"
            f"{repository}/actions/workflows/{workflow_id}/dispatches"
        ),
        data=payload,
        method="POST",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "the-compute-bazaar-sandbox-benchmark/1",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            status = response.status
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"GitHub benchmark dispatch failed ({exc.code}): {detail}"
        ) from exc
    if status != 204:
        raise RuntimeError(
            f"GitHub benchmark dispatch returned unexpected status {status}"
        )
    return {
        "requested": True,
        "repository": repository,
        "workflow_id": workflow_id,
        "ref": ref,
        "providers": providers.split(","),
        "suites": suites.split(","),
        "replicas": replica_count,
    }


def _sandbox_output_root(lake_root: str | None) -> str:
    if lake_root:
        return f"{lake_root.rstrip('/')}/sandbox_cost"
    return "data/lake/sandbox_cost"


def _repository_slug(value: str) -> str:
    parts = value.strip().split("/")
    if (
        len(parts) != 2
        or not all(parts)
        or any(not part.replace("-", "").replace("_", "").isalnum() for part in parts)
    ):
        raise ValueError("repository must be a GitHub owner/repository slug")
    return "/".join(parts)
