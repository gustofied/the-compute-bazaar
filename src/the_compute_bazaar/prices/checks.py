"""Stage checks for the GPU price platform."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .automq import check_cluster, kafka_bootstrap_servers_from_env, kafka_config_from_env
from .datafusion import query_price_index
from .gold import query_gold_price_index, read_latest_gold_manifest
from .manifest import read_latest_manifest
from .market_run import read_latest_market_run


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str
    detail: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "status": self.status, "detail": self.detail}


def run_stage1_checks(
    *,
    lake_root: str,
    provider: str = "vast",
    check_automq: bool = False,
    require_ingest_env: bool = False,
    windmill_base_url: str | None = None,
    windmill_token: str | None = None,
    windmill_workspace: str = "compute-bazaar",
    windmill_schedule_path: str = "f/compute-bazaar/market_hourly_hourly",
) -> dict[str, Any]:
    checks = [
        _check_environment(lake_root=lake_root, require_ingest_env=require_ingest_env),
        _check_latest_manifest_and_index(lake_root=lake_root, provider=provider),
        _check_latest_gold(lake_root=lake_root),
        _check_latest_market_run(lake_root=lake_root),
        _check_automq(enabled=check_automq),
        _check_windmill(
            base_url=windmill_base_url,
            token=windmill_token,
            workspace=windmill_workspace,
            schedule_path=windmill_schedule_path,
        ),
    ]
    overall = "fail" if any(check.status == "fail" for check in checks) else "ok"
    return {"overall": overall, "checks": [check.to_dict() for check in checks]}


def _check_environment(*, lake_root: str, require_ingest_env: bool) -> CheckResult:
    missing_core = []
    if not lake_root:
        missing_core.append("lake_root")
    if lake_root.startswith("s3://") and not _first_env("AWS_REGION", "AWS_DEFAULT_REGION"):
        missing_core.append("AWS_REGION or AWS_DEFAULT_REGION")

    ingest_required = [
        "COMPUTE_BAZAAR_RAW_ROOT",
        "VAST_API_KEY",
        "LIUM_API_KEY",
        "COMPUTE_BAZAAR_KAFKA_BOOTSTRAP_SERVERS",
        "COMPUTE_BAZAAR_KAFKA_USERNAME",
        "COMPUTE_BAZAAR_KAFKA_PASSWORD",
    ]
    present_ingest = sorted(key for key in ingest_required if os.getenv(key))
    missing_ingest = sorted(set(ingest_required) - set(present_ingest))
    status = "fail" if missing_core or (require_ingest_env and missing_ingest) else "ok"
    return CheckResult(
        name="environment",
        status=status,
        detail={
            "lake_root": lake_root,
            "aws_region_key": _first_present_key("AWS_REGION", "AWS_DEFAULT_REGION"),
            "missing_core": missing_core,
            "ingest_env_required": require_ingest_env,
            "present_ingest_keys": present_ingest,
            "missing_ingest_keys": missing_ingest,
        },
    )


def _check_latest_manifest_and_index(*, lake_root: str, provider: str) -> CheckResult:
    try:
        manifest = read_latest_manifest(lake_root, provider=provider)
        normalized_ref = manifest.get("normalized_ref")
        if not normalized_ref:
            return CheckResult(
                name="latest_manifest",
                status="fail",
                detail={"reason": "latest manifest has no normalized_ref", "manifest": _public_manifest(manifest)},
            )
        rows = query_price_index(parquet_uri=str(normalized_ref), limit=10)
        return CheckResult(
            name="latest_manifest_and_index",
            status="ok" if rows else "fail",
            detail={
                "manifest": _public_manifest(manifest),
                "index_rows": len(rows),
                "top": rows[:5],
            },
        )
    except Exception as exc:  # noqa: BLE001 - stage checks should report all failures as data.
        return CheckResult(name="latest_manifest_and_index", status="fail", detail={"error": str(exc)})


def _check_latest_gold(*, lake_root: str) -> CheckResult:
    try:
        manifest = read_latest_gold_manifest(lake_root)
        rows = query_gold_price_index(lake_root=lake_root, limit=10)["rows"]
        return CheckResult(
            name="latest_gold",
            status="ok" if rows else "fail",
            detail={
                "manifest": _public_gold_manifest(manifest),
                "index_rows": len(rows),
                "top": rows[:5],
            },
        )
    except Exception as exc:  # noqa: BLE001 - stage checks should report all failures as data.
        return CheckResult(name="latest_gold", status="fail", detail={"error": str(exc)})


def _check_latest_market_run(*, lake_root: str) -> CheckResult:
    try:
        manifest = read_latest_market_run(lake_root)
        checks = dict(manifest.get("checks") or {})
        failing = {
            name: status
            for name, status in checks.items()
            if status not in {"ok", "skipped", "warning"}
        }
        status = "ok" if manifest.get("status") in {"success", "warning"} and not failing else "fail"
        return CheckResult(
            name="latest_market_run",
            status=status,
            detail={
                "manifest": _public_market_run(manifest),
                "non_ok_checks": failing,
            },
        )
    except Exception as exc:  # noqa: BLE001 - stage checks should report all failures as data.
        return CheckResult(name="latest_market_run", status="fail", detail={"error": str(exc)})


def _check_automq(*, enabled: bool) -> CheckResult:
    if not enabled:
        return CheckResult(
            name="automq",
            status="skipped",
            detail={"reason": "private VPC check; rerun with --check-automq from a VPC-connected worker"},
        )
    bootstrap_servers = kafka_bootstrap_servers_from_env()
    if not bootstrap_servers:
        return CheckResult(name="automq", status="skipped", detail={"reason": "missing Kafka bootstrap servers"})
    try:
        topics = check_cluster(bootstrap_servers=bootstrap_servers, config=kafka_config_from_env())
        expected = {"gpu.provider_snapshot.v1", "gpu.normalized_offer.v1"}
        missing = sorted(expected - set(topics))
        return CheckResult(
            name="automq",
            status="ok" if not missing else "fail",
            detail={"topic_count": len(topics), "missing_expected_topics": missing},
        )
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            name="automq",
            status="fail",
            detail={
                "error": str(exc),
                "hint": "AutoMQ uses a private endpoint; run this check from the VPC worker or a VPN-connected host.",
            },
        )


def _check_windmill(
    *,
    base_url: str | None,
    token: str | None,
    workspace: str,
    schedule_path: str,
) -> CheckResult:
    if not base_url or not token:
        return CheckResult(
            name="windmill",
            status="skipped",
            detail={"reason": "set WINDMILL_BASE_URL and WINDMILL_TOKEN to check schedule"},
        )
    try:
        health = _windmill_get(base_url, "/health/status")
        schedule = _windmill_get(
            base_url,
            f"/w/{workspace}/schedules/get/{quote(schedule_path, safe='')}",
            token=token,
        )
        return CheckResult(
            name="windmill",
            status="ok" if schedule.get("enabled") else "fail",
            detail={
                "health": health,
                "schedule_path": schedule.get("path"),
                "schedule": schedule.get("schedule"),
                "enabled": schedule.get("enabled"),
            },
        )
    except Exception as exc:  # noqa: BLE001
        return CheckResult(name="windmill", status="fail", detail={"error": str(exc)})


def _windmill_get(base_url: str, path: str, *, token: str | None = None) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    request = Request(f"{base_url.rstrip('/')}/api{path}", headers=headers, method="GET")
    try:
        with urlopen(request, timeout=20) as response:
            import json

            return dict(json.loads(response.read().decode("utf-8")))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Windmill API returned {exc.code}: {body}") from exc


def _public_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider": manifest.get("provider"),
        "run_id": manifest.get("run_id"),
        "observed_at": manifest.get("observed_at"),
        "normalized_ref": manifest.get("normalized_ref"),
        "raw_offer_count": manifest.get("raw_offer_count"),
        "normalized_offer_count": manifest.get("normalized_offer_count"),
        "published_events": manifest.get("published_events"),
        "publish_mode": manifest.get("publish_mode"),
    }


def _public_gold_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": manifest.get("run_id"),
        "observed_at": manifest.get("observed_at"),
        "observed_date": manifest.get("observed_date"),
        "provider_scope": manifest.get("provider_scope"),
        "source_run_ids": manifest.get("source_run_ids"),
        "row_counts": manifest.get("row_counts"),
    }


def _public_market_run(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "market_run_id": manifest.get("market_run_id"),
        "status": manifest.get("status"),
        "observed_at": manifest.get("observed_at"),
        "providers": manifest.get("providers"),
        "provider_runs": manifest.get("provider_runs"),
        "gold_run_id": manifest.get("gold_run_id"),
        "dashboard_export_id": manifest.get("dashboard_export_id"),
        "row_counts": manifest.get("row_counts"),
        "checks": manifest.get("checks"),
    }


def _first_env(*keys: str) -> str | None:
    for key in keys:
        value = os.getenv(key)
        if value:
            return value
    return None


def _first_present_key(*keys: str) -> str | None:
    for key in keys:
        if os.getenv(key):
            return key
    return None
