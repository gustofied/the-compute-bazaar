"""Top-level market run orchestration and manifests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .events import new_run_id
from .gold import build_gold_market_tables, export_gold_dashboard_snapshot
from .pipeline import IngestResult, ingest_lium, ingest_rate_card, ingest_vast
from .providers.rate_cards import rate_card_providers
from .schemas import to_jsonable, utc_now
from .storage import list_refs, read_json, write_json


MARKET_RUN_MANIFEST_VERSION = "v1"
MARKET_RUN_TABLE = "market_runs"
DEFAULT_MARKET_PROVIDERS = ["vast", "lium", *rate_card_providers()]


@dataclass(frozen=True)
class MarketRunResult:
    market_run_id: str
    status: str
    observed_at: str
    providers: list[str]
    provider_runs: dict[str, str]
    provider_raw_refs: dict[str, str]
    provider_normalized_refs: dict[str, str | None]
    gold_run_id: str
    dashboard_export_id: str
    row_counts: dict[str, int]
    checks: dict[str, str]
    data_quality: dict[str, Any]
    provider_results: dict[str, dict[str, Any]]
    gold_manifest_ref: str
    dashboard_output_refs: dict[str, str]
    manifest_ref: str

    def to_dict(self) -> dict[str, Any]:
        return to_jsonable(self)


def run_market_hourly(
    *,
    raw_root: str = "data/raw",
    lake_root: str = "data/lake",
    dashboard_output_root: str = "data/dashboard/compute-bazaar",
    providers: list[str] | None = None,
    automq_bootstrap_servers: str | None = None,
    automq_config: dict[str, str] | None = None,
    topic_prefix: str = "gpu",
    run_id: str | None = None,
    dashboard_limit: int = 100,
    lium_size: int = 200,
    lium_paginate: bool = True,
    lium_max_pages: int = 10,
    dry_run: bool = False,
) -> MarketRunResult:
    """Run the full market heartbeat: provider ingest, gold build, dashboard export, manifest."""
    market_run_id = run_id or new_run_id("market")
    observed_at = utc_now()
    observed_date = observed_at.date().isoformat()
    provider_scope = providers or DEFAULT_MARKET_PROVIDERS

    provider_results: dict[str, IngestResult] = {}
    checks: dict[str, str] = {}
    data_quality: dict[str, Any] = {"providers": {}}

    for provider in provider_scope:
        provider_run_id = f"{provider}-{market_run_id}"
        if provider == "vast":
            result = ingest_vast(
                raw_root=raw_root,
                lake_root=lake_root,
                automq_bootstrap_servers=automq_bootstrap_servers,
                automq_config=automq_config,
                topic_prefix=topic_prefix,
                dry_run=dry_run,
                run_id=provider_run_id,
                trace_id=market_run_id,
            )
        elif provider == "lium":
            result = ingest_lium(
                raw_root=raw_root,
                lake_root=lake_root,
                automq_bootstrap_servers=automq_bootstrap_servers,
                automq_config=automq_config,
                topic_prefix=topic_prefix,
                dry_run=dry_run,
                run_id=provider_run_id,
                trace_id=market_run_id,
                query={"size": lium_size},
                paginate=lium_paginate,
                max_pages=lium_max_pages,
            )
        elif provider in rate_card_providers():
            result = ingest_rate_card(
                provider=provider,
                raw_root=raw_root,
                lake_root=lake_root,
                automq_bootstrap_servers=automq_bootstrap_servers,
                automq_config=automq_config,
                topic_prefix=topic_prefix,
                dry_run=dry_run,
                run_id=provider_run_id,
                trace_id=market_run_id,
            )
        else:
            raise ValueError(f"Unsupported market provider: {provider}")

        provider_results[provider] = result
        provider_quality = {
            "raw_offer_count": result.raw_offer_count,
            "normalized_offer_count": result.normalized_offer_count,
            "unknown_gpu_names": result.unknown_gpu_names,
            "publish_mode": result.publish_mode,
            "published_events": result.published_events,
        }
        data_quality["providers"][provider] = provider_quality
        checks[provider] = _provider_check_status(result)

    gold_run_id = f"gold-{market_run_id}"
    gold_result = build_gold_market_tables(lake_root=lake_root, providers=provider_scope, run_id=gold_run_id)
    dashboard_export_id = f"dashboard-{market_run_id}"
    dashboard_export = export_gold_dashboard_snapshot(
        lake_root=lake_root,
        output_root=dashboard_output_root,
        limit=dashboard_limit,
    )
    dashboard_output_refs = {
        **dashboard_export["output_refs"],
        "market_run": _dashboard_market_run_ref(dashboard_output_root),
        "market_history": _dashboard_market_history_ref(dashboard_output_root),
    }

    row_counts = {
        "listings": gold_result.row_counts.get("fact_gpu_listings", 0),
        "gpu_products": gold_result.row_counts.get("dim_gpu_products", 0),
        "index_values": gold_result.row_counts.get("fact_price_index_values", 0),
        "index_constituents": gold_result.row_counts.get("fact_index_constituents", 0),
    }
    checks["gold"] = "ok" if all(value > 0 for value in row_counts.values()) else "warning"
    checks["dashboard_export"] = "ok" if dashboard_export.get("output_refs") else "warning"
    status = "success" if all(value == "ok" for value in checks.values()) else "warning"

    payload = {
        "manifest_version": MARKET_RUN_MANIFEST_VERSION,
        "table": MARKET_RUN_TABLE,
        "market_run_id": market_run_id,
        "status": status,
        "observed_at": observed_at.isoformat(),
        "observed_date": observed_date,
        "providers": provider_scope,
        "provider_runs": {provider: result.run_id for provider, result in provider_results.items()},
        "provider_raw_refs": {provider: result.raw_ref for provider, result in provider_results.items()},
        "provider_normalized_refs": {
            provider: result.normalized_ref for provider, result in provider_results.items()
        },
        "provider_manifest_refs": {
            provider: result.manifest_ref for provider, result in provider_results.items()
        },
        "gold_run_id": gold_result.run_id,
        "gold_manifest_ref": gold_result.manifest_ref,
        "dashboard_export_id": dashboard_export_id,
        "dashboard_output_refs": dashboard_output_refs,
        "row_counts": row_counts,
        "gold_row_counts": gold_result.row_counts,
        "checks": checks,
        "data_quality": data_quality,
    }
    manifest_ref = write_market_run_manifest(
        lake_root=lake_root,
        observed_date=observed_date,
        market_run_id=market_run_id,
        payload=payload,
    )
    payload["manifest_ref"] = manifest_ref
    write_dashboard_market_run_snapshots(
        lake_root=lake_root,
        output_root=dashboard_output_root,
        latest=payload,
    )

    return MarketRunResult(
        market_run_id=market_run_id,
        status=status,
        observed_at=observed_at.isoformat(),
        providers=provider_scope,
        provider_runs={provider: result.run_id for provider, result in provider_results.items()},
        provider_raw_refs={provider: result.raw_ref for provider, result in provider_results.items()},
        provider_normalized_refs={
            provider: result.normalized_ref for provider, result in provider_results.items()
        },
        gold_run_id=gold_result.run_id,
        dashboard_export_id=dashboard_export_id,
        row_counts=row_counts,
        checks=checks,
        data_quality=data_quality,
        provider_results={provider: result.to_dict() for provider, result in provider_results.items()},
        gold_manifest_ref=gold_result.manifest_ref,
        dashboard_output_refs=dashboard_output_refs,
        manifest_ref=manifest_ref,
    )


def write_market_run_manifest(
    *,
    lake_root: str,
    observed_date: str,
    market_run_id: str,
    payload: dict[str, Any],
) -> str:
    manifest_ref = market_run_manifest_ref(
        lake_root,
        observed_date=observed_date,
        market_run_id=market_run_id,
    )
    payload_with_ref = dict(payload)
    payload_with_ref["manifest_ref"] = manifest_ref
    write_json(manifest_ref, payload_with_ref)
    write_json(latest_market_run_ref(lake_root), payload_with_ref)
    return manifest_ref


def read_latest_market_run(lake_root: str) -> dict[str, Any]:
    return dict(read_json(latest_market_run_ref(lake_root)))


def list_market_runs(lake_root: str, *, limit: int = 24) -> list[dict[str, Any]]:
    requested_limit = max(1, int(limit))
    refs = [
        ref
        for ref in list_refs(market_runs_manifest_prefix(lake_root), suffix=".json")
        if "/run_id=" in ref or "/run_id%3D" in ref
    ]
    manifests: list[dict[str, Any]] = []
    for ref in reversed(refs):
        try:
            manifest = dict(read_json(ref))
        except Exception:  # noqa: BLE001 - a partial/bad manifest should not hide the good history.
            continue
        manifests.append(manifest)
        if len(manifests) >= requested_limit:
            break

    manifests.sort(key=lambda row: str(row.get("observed_at") or ""), reverse=True)
    return manifests[:requested_limit]


def write_dashboard_market_run_snapshots(
    *,
    lake_root: str,
    output_root: str,
    latest: dict[str, Any] | None = None,
    limit: int = 24,
) -> dict[str, str]:
    latest_manifest = latest or read_latest_market_run(lake_root)
    history = [_public_market_run_manifest(row) for row in list_market_runs(lake_root, limit=limit)]
    if not history:
        history = [_public_market_run_manifest(latest_manifest)]

    output_refs = {
        "market_run": _dashboard_market_run_ref(output_root),
        "market_history": _dashboard_market_history_ref(output_root),
    }
    write_json(output_refs["market_run"], _public_market_run_manifest(latest_manifest))
    write_json(
        output_refs["market_history"],
        {
            "latest_market_run_id": latest_manifest.get("market_run_id"),
            "row_count": len(history),
            "rows": history,
        },
    )
    return output_refs


def latest_market_run_ref(lake_root: str) -> str:
    return "/".join([lake_root.rstrip("/"), "_manifests", MARKET_RUN_TABLE, "latest.json"])


def market_runs_manifest_prefix(lake_root: str) -> str:
    return "/".join([lake_root.rstrip("/"), "_manifests", MARKET_RUN_TABLE])


def market_run_manifest_ref(lake_root: str, *, observed_date: str, market_run_id: str) -> str:
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
    if result.normalized_offer_count <= 0 or result.published_events <= 0:
        return "error"
    if result.unknown_gpu_names:
        return "warning"
    return "ok"


def _dashboard_market_run_ref(output_root: str) -> str:
    return "/".join([output_root.rstrip("/"), "market-run.json"])


def _dashboard_market_history_ref(output_root: str) -> str:
    return "/".join([output_root.rstrip("/"), "market-history.json"])


def _public_market_run_manifest(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "manifest_version": payload.get("manifest_version"),
        "market_run_id": payload.get("market_run_id"),
        "status": payload.get("status"),
        "observed_at": payload.get("observed_at"),
        "observed_date": payload.get("observed_date"),
        "providers": payload.get("providers"),
        "provider_runs": payload.get("provider_runs"),
        "gold_run_id": payload.get("gold_run_id"),
        "dashboard_export_id": payload.get("dashboard_export_id"),
        "row_counts": payload.get("row_counts"),
        "checks": payload.get("checks"),
        "data_quality": payload.get("data_quality"),
    }
