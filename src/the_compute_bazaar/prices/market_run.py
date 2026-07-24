"""Top-level market run orchestration and manifests."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from the_compute_bazaar.sandbox_cost.pipeline import build_sandbox_cost

from .coverage import query_frontier_coverage_ref
from .events import new_run_id
from .gold import build_gold_market_tables, export_gold_dashboard_snapshot
from .pipeline import (
    IngestResult,
    ingest_akash,
    ingest_aws_spot,
    ingest_azure_retail,
    ingest_clore,
    ingest_cloud_gpu_prices,
    ingest_digitalocean,
    ingest_gpus_io,
    ingest_getdeploying,
    ingest_gridstackhub,
    ingest_hyperstack,
    ingest_inference_sh,
    ingest_jarvislabs,
    ingest_lambda_cloud,
    ingest_lium,
    ingest_oracle_cloud,
    ingest_ovhcloud,
    ingest_prime_intellect,
    ingest_rate_card,
    ingest_runpod,
    ingest_scaleway,
    ingest_sesterce,
    ingest_shadeform,
    ingest_spheron,
    ingest_tensordock,
    ingest_thunder_compute,
    ingest_verda,
    ingest_vast,
    ingest_vultr,
)
from .providers.rate_cards import DEFAULT_RATE_CARD_PROVIDER, rate_card_providers
from .schemas import to_jsonable, utc_now
from .storage import list_refs, read_json, write_json


MARKET_RUN_MANIFEST_VERSION = "v1"
MARKET_RUN_TABLE = "market_runs"
OPTIONAL_API_PROVIDERS = {
    "prime_intellect": "PRIME_INTELLECT_API_KEY",
    "shadeform": "SHADEFORM_API_KEY",
    "sesterce": "SESTERCE_API_KEY",
    "tensordock": "TENSORDOCK_API_KEY",
    "hyperstack": "HYPERSTACK_API_KEY",
    "lambda": "LAMBDA_CLOUD_API_KEY",
    "digitalocean": "DIGITALOCEAN_API_TOKEN",
    "gpus_io": "GPUS_IO_API_KEY",
    "getdeploying": "GETDEPLOYING_API_KEY",
    "jarvislabs": "JL_API_KEY",
}


def default_market_providers() -> list[str]:
    providers = [
        "vast",
        "lium",
        "spheron",
        "inference_sh",
        "gridstackhub",
        "cloud_gpu_prices",
        "thunder_compute",
        "vultr",
        "scaleway",
        "oracle_cloud",
        "ovhcloud",
        "clore",
        "akash",
        "aws_spot",
        "azure",
        "runpod",
        "verda",
        DEFAULT_RATE_CARD_PROVIDER,
    ]
    providers.extend(
        provider
        for provider, env_name in OPTIONAL_API_PROVIDERS.items()
        if os.getenv(env_name)
    )
    return providers


@dataclass(frozen=True)
class MarketRunResult:
    market_run_id: str
    status: str
    observed_at: str
    providers: list[str]
    successful_providers: list[str]
    failed_providers: list[str]
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
    provider_scope = list(dict.fromkeys(providers or default_market_providers()))

    provider_results: dict[str, IngestResult] = {}
    checks: dict[str, str] = {}
    data_quality: dict[str, Any] = {"providers": {}}

    for provider in provider_scope:
        try:
            result = _ingest_market_provider(
                provider=provider,
                market_run_id=market_run_id,
                raw_root=raw_root,
                lake_root=lake_root,
                automq_bootstrap_servers=automq_bootstrap_servers,
                automq_config=automq_config,
                topic_prefix=topic_prefix,
                lium_size=lium_size,
                lium_paginate=lium_paginate,
                lium_max_pages=lium_max_pages,
                dry_run=dry_run,
            )
        except Exception as exc:  # noqa: BLE001 - providers are isolated at the run boundary.
            checks[provider] = "error"
            data_quality["providers"][provider] = {
                "status": "error",
                "error_type": type(exc).__name__,
                "error": _provider_error_message(exc),
            }
            continue

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

    successful_providers = [
        provider
        for provider in provider_scope
        if provider in provider_results
        and provider_results[provider].normalized_ref
        and provider_results[provider].normalized_offer_count > 0
    ]
    failed_providers = [
        provider for provider in provider_scope if provider not in successful_providers
    ]
    data_quality["successful_providers"] = successful_providers
    data_quality["failed_providers"] = failed_providers
    if not successful_providers:
        raise RuntimeError(
            "All market providers failed or returned no normalized offers"
        )

    gold_run_id = f"gold-{market_run_id}"
    gold_result = build_gold_market_tables(
        lake_root=lake_root,
        providers=successful_providers,
        run_id=gold_run_id,
    )
    data_quality["frontier_coverage"] = query_frontier_coverage_ref(
        table_ref=gold_result.table_refs["fact_gpu_listings"],
    )
    dashboard_export_id = f"dashboard-{market_run_id}"
    dashboard_export = export_gold_dashboard_snapshot(
        lake_root=lake_root,
        output_root=dashboard_output_root,
        limit=dashboard_limit,
    )
    sandbox_cost = build_sandbox_cost(
        output_root="/".join([lake_root.rstrip("/"), "sandbox_cost"]),
        dashboard_output_root=dashboard_output_root,
        gpu_history_ref=dashboard_export["output_refs"]["benchmark_history"],
    )
    dashboard_output_refs = {
        **dashboard_export["output_refs"],
        "sandbox_cost": str(sandbox_cost.public_ref),
        "market_run": _dashboard_market_run_ref(dashboard_output_root),
        "market_history": _dashboard_market_history_ref(dashboard_output_root),
    }

    row_counts = {
        "listings": gold_result.row_counts.get("fact_gpu_listings", 0),
        "gpu_products": gold_result.row_counts.get("dim_gpu_products", 0),
        "index_values": gold_result.row_counts.get("fact_price_index_values", 0),
        "index_constituents": gold_result.row_counts.get("fact_index_constituents", 0),
        "sandbox_price_observations": sandbox_cost.row_counts.get(
            "sandbox_hourly_price_series", 0
        ),
        "sandbox_benchmark_results": sandbox_cost.row_counts.get(
            "sandbox_workload_latest_replicates", 0
        ),
    }
    checks["gold"] = (
        "ok" if all(value > 0 for value in row_counts.values()) else "warning"
    )
    checks["dashboard_export"] = (
        "ok" if dashboard_export.get("output_refs") else "warning"
    )
    checks["sandbox_cost"] = (
        "ok"
        if sandbox_cost.public_ref
        and sandbox_cost.row_counts.get("sandbox_gpu_cpu_common_start", 0) > 0
        else "warning"
    )
    data_quality["sandbox_cost"] = {
        "build_id": sandbox_cost.build_id,
        "row_counts": sandbox_cost.row_counts,
        "manifest_ref": sandbox_cost.manifest_ref,
    }
    status = "success" if all(value == "ok" for value in checks.values()) else "warning"

    payload = {
        "manifest_version": MARKET_RUN_MANIFEST_VERSION,
        "table": MARKET_RUN_TABLE,
        "market_run_id": market_run_id,
        "status": status,
        "observed_at": observed_at.isoformat(),
        "observed_date": observed_date,
        "providers": provider_scope,
        "successful_providers": successful_providers,
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
        "provider_manifest_refs": {
            provider: result.manifest_ref
            for provider, result in provider_results.items()
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
        successful_providers=successful_providers,
        failed_providers=failed_providers,
        provider_runs={
            provider: result.run_id for provider, result in provider_results.items()
        },
        provider_raw_refs={
            provider: result.raw_ref for provider, result in provider_results.items()
        },
        provider_normalized_refs={
            provider: result.normalized_ref
            for provider, result in provider_results.items()
        },
        gold_run_id=gold_result.run_id,
        dashboard_export_id=dashboard_export_id,
        row_counts=row_counts,
        checks=checks,
        data_quality=data_quality,
        provider_results={
            provider: result.to_dict() for provider, result in provider_results.items()
        },
        gold_manifest_ref=gold_result.manifest_ref,
        dashboard_output_refs=dashboard_output_refs,
        manifest_ref=manifest_ref,
    )


def _ingest_market_provider(
    *,
    provider: str,
    market_run_id: str,
    raw_root: str,
    lake_root: str,
    automq_bootstrap_servers: str | None,
    automq_config: dict[str, str] | None,
    topic_prefix: str,
    lium_size: int,
    lium_paginate: bool,
    lium_max_pages: int,
    dry_run: bool,
) -> IngestResult:
    common_kwargs = {
        "raw_root": raw_root,
        "lake_root": lake_root,
        "automq_bootstrap_servers": automq_bootstrap_servers,
        "automq_config": automq_config,
        "topic_prefix": topic_prefix,
        "dry_run": dry_run,
        "run_id": f"{provider}-{market_run_id}",
        "trace_id": market_run_id,
    }
    if provider == "vast":
        return ingest_vast(**common_kwargs)
    if provider == "lium":
        return ingest_lium(
            **common_kwargs,
            query={"size": lium_size},
            paginate=lium_paginate,
            max_pages=lium_max_pages,
        )
    if provider == "aws_spot":
        return ingest_aws_spot(**common_kwargs)
    if provider == "azure":
        return ingest_azure_retail(**common_kwargs)
    if provider == "spheron":
        return ingest_spheron(**common_kwargs)
    if provider == "inference_sh":
        return ingest_inference_sh(**common_kwargs)
    if provider == "gridstackhub":
        return ingest_gridstackhub(**common_kwargs)
    if provider == "cloud_gpu_prices":
        return ingest_cloud_gpu_prices(**common_kwargs)
    if provider == "getdeploying":
        return ingest_getdeploying(**common_kwargs)
    if provider == "thunder_compute":
        return ingest_thunder_compute(**common_kwargs)
    if provider == "vultr":
        return ingest_vultr(**common_kwargs)
    if provider == "scaleway":
        return ingest_scaleway(**common_kwargs)
    if provider == "oracle_cloud":
        return ingest_oracle_cloud(**common_kwargs)
    if provider == "ovhcloud":
        return ingest_ovhcloud(**common_kwargs)
    if provider == "gpus_io":
        return ingest_gpus_io(**common_kwargs)
    if provider == "clore":
        return ingest_clore(**common_kwargs)
    if provider == "verda":
        return ingest_verda(**common_kwargs)
    if provider == "akash":
        return ingest_akash(**common_kwargs)
    if provider == "prime_intellect":
        return ingest_prime_intellect(**common_kwargs)
    if provider == "shadeform":
        return ingest_shadeform(**common_kwargs)
    if provider == "sesterce":
        return ingest_sesterce(**common_kwargs)
    if provider == "runpod":
        return ingest_runpod(**common_kwargs)
    if provider == "tensordock":
        return ingest_tensordock(**common_kwargs)
    if provider == "hyperstack":
        return ingest_hyperstack(**common_kwargs)
    if provider == "lambda":
        return ingest_lambda_cloud(**common_kwargs)
    if provider == "digitalocean":
        return ingest_digitalocean(**common_kwargs)
    if provider == "jarvislabs":
        return ingest_jarvislabs(**common_kwargs)
    if provider == DEFAULT_RATE_CARD_PROVIDER:
        return ingest_rate_card(provider=DEFAULT_RATE_CARD_PROVIDER, **common_kwargs)
    if provider in rate_card_providers():
        return ingest_rate_card(provider=provider, **common_kwargs)
    raise ValueError(f"Unsupported market provider: {provider}")


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
    history = [
        _public_market_run_manifest(row)
        for row in list_market_runs(lake_root, limit=limit)
    ]
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
    if result.normalized_offer_count <= 0 or result.published_events <= 0:
        return "error"
    if result.unknown_gpu_names:
        return "warning"
    return "ok"


def _provider_error_message(exc: Exception) -> str:
    message = " ".join(str(exc).split())
    return message[:500] or type(exc).__name__


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
        "successful_providers": payload.get("successful_providers"),
        "failed_providers": payload.get("failed_providers"),
        "provider_runs": payload.get("provider_runs"),
        "gold_run_id": payload.get("gold_run_id"),
        "dashboard_export_id": payload.get("dashboard_export_id"),
        "row_counts": payload.get("row_counts"),
        "checks": payload.get("checks"),
        "data_quality": payload.get("data_quality"),
    }
