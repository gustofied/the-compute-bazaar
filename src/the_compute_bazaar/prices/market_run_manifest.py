"""Persist, list, and sanitize market-run manifests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..contracts import MARKET_RUN_CONTRACT, require_contract
from .ingestion import IngestResult
from .storage import list_refs, read_json, write_json


MARKET_RUN_TABLE = "market_runs"


@dataclass(frozen=True)
class MarketRunHistory:
    rows: list[dict[str, Any]]
    skipped_manifest_count: int


def write_market_run_manifest(
    *,
    lake_root: str,
    observed_date: str,
    market_run_id: str,
    payload: dict[str, Any],
    update_latest: bool = True,
) -> str:
    manifest_ref = market_run_manifest_ref(
        lake_root,
        observed_date=observed_date,
        market_run_id=market_run_id,
    )
    payload_with_ref = dict(payload)
    payload_with_ref["manifest_ref"] = manifest_ref
    write_json(manifest_ref, payload_with_ref)
    if update_latest:
        write_json(latest_market_run_ref(lake_root), payload_with_ref)
    return manifest_ref


def _failed_market_run_payload(
    *,
    market_run_id: str,
    observed_at: str,
    observed_date: str,
    provider_scope: list[str],
    failed_providers: list[str],
    checks: dict[str, str],
    data_quality: dict[str, Any],
    provider_results: dict[str, IngestResult],
) -> dict[str, Any]:
    return {
        "contract": MARKET_RUN_CONTRACT,
        "table": MARKET_RUN_TABLE,
        "market_run_id": market_run_id,
        "status": "failed",
        "data_quality_status": "error",
        "observed_at": observed_at,
        "observed_date": observed_date,
        "providers": provider_scope,
        "successful_providers": [],
        "failed_providers": failed_providers,
        "provider_runs": {
            provider: result.run_id for provider, result in provider_results.items()
        },
        "provider_raw_refs": {
            provider: result.raw_ref for provider, result in provider_results.items()
        },
        "provider_normalized_refs": {
            provider: result.normalized_ref
            for provider, result in provider_results.items()
        },
        "provider_market_state_refs": {
            provider: result.market_state_ref
            for provider, result in provider_results.items()
        },
        "gold_run_id": None,
        "row_counts": {},
        "checks": checks,
        "data_quality": data_quality,
    }


def read_latest_market_run(lake_root: str) -> dict[str, Any]:
    return _read_market_run_manifest(latest_market_run_ref(lake_root))


def read_market_run_history(lake_root: str, *, limit: int = 24) -> MarketRunHistory:
    requested_limit = max(1, int(limit))
    refs = [
        ref
        for ref in list_refs(market_runs_manifest_prefix(lake_root), suffix=".json")
        if "/run_id=" in ref or "/run_id%3D" in ref
    ]
    manifests: list[dict[str, Any]] = []
    skipped_manifest_count = 0
    for ref in refs:
        try:
            manifest = _read_market_run_manifest(ref)
        except Exception:
            skipped_manifest_count += 1
            continue
        manifests.append(manifest)

    manifests.sort(key=lambda row: str(row.get("observed_at") or ""), reverse=True)
    return MarketRunHistory(
        rows=manifests[:requested_limit],
        skipped_manifest_count=skipped_manifest_count,
    )


def _read_market_run_manifest(ref: str) -> dict[str, Any]:
    manifest = dict(read_json(ref))
    require_contract(manifest, contract=MARKET_RUN_CONTRACT)
    return manifest


def write_public_market_run_snapshots(
    *,
    lake_root: str,
    output_root: str,
    latest: dict[str, Any] | None = None,
    limit: int = 24,
) -> dict[str, str]:
    latest_manifest = latest or read_latest_market_run(lake_root)
    market_history = read_market_run_history(lake_root, limit=limit)
    history = [_public_market_run_manifest(row) for row in market_history.rows]
    if not history:
        history = [_public_market_run_manifest(latest_manifest)]

    output_refs = {
        "market_run": _public_market_run_ref(output_root),
        "market_history": _public_market_history_ref(output_root),
    }
    write_json(output_refs["market_run"], _public_market_run_manifest(latest_manifest))
    write_json(
        output_refs["market_history"],
        {
            "latest_market_run_id": latest_manifest.get("market_run_id"),
            "row_count": len(history),
            "skipped_manifest_count": market_history.skipped_manifest_count,
            "rows": history,
        },
    )
    return output_refs


def latest_market_run_ref(lake_root: str) -> str:
    return "/".join(
        [lake_root.rstrip("/"), "_manifests", MARKET_RUN_TABLE, "latest.json"]
    )


def market_runs_manifest_prefix(lake_root: str) -> str:
    return "/".join([lake_root.rstrip("/"), "_manifests", MARKET_RUN_TABLE])


def market_run_manifest_ref(
    lake_root: str, *, observed_date: str, market_run_id: str
) -> str:
    return "/".join(
        [
            lake_root.rstrip("/"),
            "_manifests",
            MARKET_RUN_TABLE,
            f"date={observed_date}",
            f"run_id={market_run_id}.json",
        ]
    )


def _provider_check_status(result: IngestResult) -> str:
    if result.normalized_observation_count <= 0 or result.published_events <= 0:
        return "error"
    return "ok"


def _provider_error_message(exc: Exception) -> str:
    message = " ".join(str(exc).split())
    return message[:500] or type(exc).__name__


def _public_market_run_ref(output_root: str) -> str:
    return "/".join([output_root.rstrip("/"), "market-run.json"])


def _public_market_history_ref(output_root: str) -> str:
    return "/".join([output_root.rstrip("/"), "market-history.json"])


def _public_market_run_manifest(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract": MARKET_RUN_CONTRACT,
        "market_run_id": payload.get("market_run_id"),
        "status": payload.get("status"),
        "data_quality_status": payload.get("data_quality_status"),
        "observed_at": payload.get("observed_at"),
        "observed_date": payload.get("observed_date"),
        "providers": payload.get("providers"),
        "successful_providers": payload.get("successful_providers"),
        "failed_providers": payload.get("failed_providers"),
        "provider_runs": payload.get("provider_runs"),
        "gold_run_id": payload.get("gold_run_id"),
        "row_counts": payload.get("row_counts"),
        "checks": payload.get("checks"),
        "data_quality": _without_private_refs(payload.get("data_quality")),
    }


def _without_private_refs(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: cleaned
            for key, item in value.items()
            if (cleaned := _without_private_refs(item)) is not None
        }
    if isinstance(value, list):
        return [
            cleaned
            for item in value
            if (cleaned := _without_private_refs(item)) is not None
        ]
    if isinstance(value, str) and value.startswith("s3://"):
        return None
    return value
