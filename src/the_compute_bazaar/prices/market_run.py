"""Execute one provider-to-publication market observation cycle."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..contracts import MARKET_RUN_CONTRACT
from ..portable_lake import publish_portable_lake
from .coverage import query_frontier_coverage_ref
from .events import new_run_id
from .gold import build_gold_market_tables
from .ingestion import IngestResult
from .market_run_manifest import (
    _failed_market_run_payload,
    _provider_check_status,
    _provider_error_message,
    _public_market_history_ref,
    _public_market_run_ref,
    write_market_run_manifest,
    write_public_market_run_snapshots,
)
from .provider_registry import ProviderRunContext, enabled_provider_names, get_provider
from .public_exports import export_public_cards
from .schemas import to_jsonable, utc_now


MARKET_RUN_TABLE = "market_runs"


def default_market_providers() -> list[str]:
    return enabled_provider_names()


@dataclass(frozen=True)
class MarketRunResult:
    market_run_id: str
    status: str
    data_quality_status: str
    observed_at: str
    providers: list[str]
    successful_providers: list[str]
    failed_providers: list[str]
    provider_runs: dict[str, str]
    provider_raw_refs: dict[str, str]
    provider_normalized_refs: dict[str, str | None]
    provider_market_state_refs: dict[str, str | None]
    gold_run_id: str
    row_counts: dict[str, int]
    checks: dict[str, str]
    data_quality: dict[str, Any]
    provider_results: dict[str, dict[str, Any]]
    gold_manifest_ref: str
    public_output_refs: dict[str, str]
    manifest_ref: str

    def to_dict(self) -> dict[str, Any]:
        return to_jsonable(self)


def run_market_hourly(
    *,
    raw_root: str = "data/raw",
    lake_root: str = "data/lake",
    dashboard_output_root: str = "data/dashboard/compute-bazaar",
    providers: list[str] | None = None,
    required_providers: list[str] | None = None,
    minimum_successful_providers: int = 1,
    automq_bootstrap_servers: str | None = None,
    automq_config: dict[str, str] | None = None,
    topic_prefix: str = "gpu",
    run_id: str | None = None,
    provider_options: Mapping[str, Mapping[str, Any]] | None = None,
    dry_run: bool = False,
) -> MarketRunResult:
    """Run the full market heartbeat: ingest, Gold, public cards, portable lake."""
    market_run_id = run_id or new_run_id("market")
    observed_at = utc_now()
    observed_date = observed_at.date().isoformat()
    provider_scope = list(dict.fromkeys(providers or default_market_providers()))
    required_provider_scope = list(dict.fromkeys(required_providers or []))
    unknown_required_providers = set(required_provider_scope) - set(provider_scope)
    if unknown_required_providers:
        raise ValueError(
            "Required providers are outside the market cohort: "
            + ", ".join(sorted(unknown_required_providers))
        )
    if minimum_successful_providers < 1:
        raise ValueError("minimum_successful_providers must be at least 1")
    if minimum_successful_providers > len(provider_scope):
        raise ValueError(
            "minimum_successful_providers cannot exceed the provider cohort"
        )
    unknown_option_providers = set(provider_options or {}) - set(provider_scope)
    if unknown_option_providers:
        raise ValueError(
            "Provider options supplied outside the market cohort: "
            + ", ".join(sorted(unknown_option_providers))
        )

    provider_results: dict[str, IngestResult] = {}
    checks: dict[str, str] = {}
    data_quality: dict[str, Any] = {"providers": {}}
    provider_context = ProviderRunContext(
        market_run_id=market_run_id,
        raw_root=raw_root,
        lake_root=lake_root,
        automq_bootstrap_servers=automq_bootstrap_servers,
        automq_config=automq_config or {},
        topic_prefix=topic_prefix,
        dry_run=dry_run,
        provider_options=provider_options or {},
    )

    for provider in provider_scope:
        try:
            result = _ingest_market_provider(
                provider=provider,
                context=provider_context,
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
            "normalized_observation_count": result.normalized_observation_count,
            "unknown_gpu_names": result.unknown_gpu_names,
            "operational_status": "ok",
            "normalization_status": ("warning" if result.unknown_gpu_names else "ok"),
            "publish_mode": result.publish_mode,
            "published_events": result.published_events,
            "market_state_observation_count": result.market_state_observation_count,
        }
        data_quality["providers"][provider] = provider_quality
        checks[provider] = _provider_check_status(result)

    successful_providers = [
        provider
        for provider in provider_scope
        if provider in provider_results
        and provider_results[provider].normalized_ref
        and provider_results[provider].normalized_observation_count > 0
    ]
    failed_providers = [
        provider for provider in provider_scope if provider not in successful_providers
    ]
    missing_required_providers = [
        provider
        for provider in required_provider_scope
        if provider not in successful_providers
    ]
    cohort_is_viable = (
        len(successful_providers) >= minimum_successful_providers
        and not missing_required_providers
    )
    data_quality["successful_providers"] = successful_providers
    data_quality["failed_providers"] = failed_providers
    data_quality["cohort"] = {
        "required_providers": required_provider_scope,
        "optional_providers": [
            provider
            for provider in provider_scope
            if provider not in required_provider_scope
        ],
        "minimum_successful_providers": minimum_successful_providers,
        "missing_required_providers": missing_required_providers,
        "status": (
            "complete"
            if not failed_providers
            else "degraded"
            if cohort_is_viable
            else "failed"
        ),
    }
    normalization_warnings = {
        provider: quality["unknown_gpu_names"]
        for provider, quality in data_quality["providers"].items()
        if quality.get("unknown_gpu_names")
    }
    data_quality_status = (
        "warning" if normalization_warnings or failed_providers else "ok"
    )
    data_quality["status"] = data_quality_status
    data_quality["normalization_warnings"] = normalization_warnings
    if not cohort_is_viable:
        data_quality["status"] = "error"
        failure_payload = _failed_market_run_payload(
            market_run_id=market_run_id,
            observed_at=observed_at.isoformat(),
            observed_date=observed_date,
            provider_scope=provider_scope,
            failed_providers=failed_providers,
            checks=checks,
            data_quality=data_quality,
            provider_results=provider_results,
        )
        write_market_run_manifest(
            lake_root=lake_root,
            observed_date=observed_date,
            market_run_id=market_run_id,
            payload=failure_payload,
            update_latest=False,
        )
        raise RuntimeError("Market provider cohort did not meet its publication policy")

    gold_run_id = f"gold-{market_run_id}"
    gold_result = build_gold_market_tables(
        lake_root=lake_root,
        providers=successful_providers,
        run_id=gold_run_id,
    )
    data_quality["frontier_coverage"] = query_frontier_coverage_ref(
        table_ref=gold_result.table_refs["fact_gpu_listings"],
    )
    public_export = export_public_cards(
        lake_root=lake_root,
        output_root=dashboard_output_root,
    )
    public_output_refs = {
        **public_export["output_refs"],
        "market_run": _public_market_run_ref(dashboard_output_root),
        "market_history": _public_market_history_ref(dashboard_output_root),
    }
    portable_lake = publish_portable_lake(
        source_lake_root=lake_root,
        output_root=f"{dashboard_output_root.rstrip('/')}/lake",
    )
    public_output_refs["portable_lake"] = portable_lake["index_ref"]

    row_counts = {
        "listings": gold_result.row_counts.get("fact_gpu_listings", 0),
        "gpu_products": gold_result.row_counts.get("dim_gpu_products", 0),
        "gpu_price_index": gold_result.row_counts.get("fact_gpu_price_index", 0),
        "gpu_price_index_constituents": gold_result.row_counts.get(
            "fact_gpu_price_index_constituents", 0
        ),
        "compute_market_state": gold_result.row_counts.get(
            "fact_compute_market_state", 0
        ),
    }
    checks["gold"] = (
        "ok" if all(value > 0 for value in row_counts.values()) else "warning"
    )
    checks["public_cards"] = "ok" if public_export.get("output_refs") else "warning"
    checks["portable_lake"] = "ok" if portable_lake.get("file_count") else "warning"
    status = "success" if all(value == "ok" for value in checks.values()) else "warning"

    payload = {
        "contract": MARKET_RUN_CONTRACT,
        "table": MARKET_RUN_TABLE,
        "market_run_id": market_run_id,
        "status": status,
        "data_quality_status": data_quality_status,
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
        "provider_market_state_refs": {
            provider: result.market_state_ref
            for provider, result in provider_results.items()
        },
        "provider_manifest_refs": {
            provider: result.manifest_ref
            for provider, result in provider_results.items()
        },
        "gold_run_id": gold_result.run_id,
        "gold_manifest_ref": gold_result.manifest_ref,
        "public_output_refs": public_output_refs,
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
    write_public_market_run_snapshots(
        lake_root=lake_root,
        output_root=dashboard_output_root,
        latest=payload,
    )

    return MarketRunResult(
        market_run_id=market_run_id,
        status=status,
        data_quality_status=data_quality_status,
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
        provider_market_state_refs={
            provider: result.market_state_ref
            for provider, result in provider_results.items()
        },
        gold_run_id=gold_result.run_id,
        row_counts=row_counts,
        checks=checks,
        data_quality=data_quality,
        provider_results={
            provider: result.to_dict() for provider, result in provider_results.items()
        },
        gold_manifest_ref=gold_result.manifest_ref,
        public_output_refs=public_output_refs,
        manifest_ref=manifest_ref,
    )


def _ingest_market_provider(
    *,
    provider: str,
    context: ProviderRunContext,
) -> IngestResult:
    return get_provider(provider).ingest(context)
