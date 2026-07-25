"""Normalize source-honest compute rental and availability observations."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from .normalize import canonical_gpu_model
from .schemas import ComputeMarketState


AKASH_PROVIDERS_URL = "https://console-api.akash.network/v1/providers"
AKASH_GPU_PRICES_URL = "https://console-api.akash.network/v1/gpu-prices"
CLORE_MARKETPLACE_URL = "https://api.clore.ai/v1/marketplace"
PRIME_AVAILABILITY_URL = "https://api.primeintellect.ai/api/v1/availability/gpus"
RUNPOD_GRAPHQL_URL = "https://api.runpod.io/graphql"
HYPERSTACK_STOCK_URL = "https://infrahub-api.nexgencloud.com/v1/core/stocks"

PROVIDER_ALIASES = {
    "lambda_labs": "lambda",
    "lambdalabs": "lambda",
    "massed_compute": "massed_compute",
    "massedcompute": "massed_compute",
}


def normalize_akash_market_state(
    *,
    models: Iterable[Mapping[str, Any]],
    providers: Iterable[Mapping[str, Any]],
    observed_at: datetime,
    raw_ref: str | None,
) -> list[ComputeMarketState]:
    """Build network rental occupancy and model availability from Akash."""
    rows: list[ComputeMarketState] = []
    online_provider_count = 0
    total = active = available = pending = 0.0

    for provider in providers:
        if provider.get("isOnline") is not True:
            continue
        stats = provider.get("stats")
        gpu = stats.get("gpu") if isinstance(stats, Mapping) else None
        if not isinstance(gpu, Mapping):
            continue
        provider_total = _float_or_none(gpu.get("total"))
        if provider_total is None or provider_total < 0:
            continue
        online_provider_count += 1
        total += provider_total
        active += _float_or_zero(gpu.get("active"))
        available += _float_or_zero(gpu.get("available"))
        pending += _float_or_zero(gpu.get("pending"))

    if total > 0:
        rows.append(
            _state(
                observed_at=observed_at,
                resource_type="ALL_GPU",
                provider="akash",
                source_connector="akash",
                source_role="direct",
                measurement_kind="rental_occupancy",
                measurement_scope="online_provider_gpu_units",
                unit="gpu_units",
                total_units=total,
                rented_units=active,
                available_units=available,
                pending_units=pending,
                rented_share=_share(active, total),
                available_share=_share(available, total),
                stock_status=None,
                count_precision="reported_counts",
                numerator_definition="GPU units reported active (currently leased) by online Akash providers.",
                denominator_definition="Total GPU units reported by the same online Akash providers.",
                source_url=AKASH_PROVIDERS_URL,
                raw_ref=raw_ref,
                notes=f"Aggregated across {online_provider_count} online providers.",
            )
        )

    for model in models:
        gpu_name = str(model.get("model") or "").strip()
        vram_gb = _gib_value(model.get("ram"))
        gpu_model = canonical_gpu_model(
            gpu_name,
            vram_gb * 1024 if vram_gb is not None else None,
        )
        availability_row = model.get("availability")
        if not gpu_model or not isinstance(availability_row, Mapping):
            continue
        model_total = _float_or_none(availability_row.get("total"))
        model_available = _float_or_none(availability_row.get("available"))
        if model_total is None or model_total <= 0 or model_available is None:
            continue
        rows.append(
            _state(
                observed_at=observed_at,
                resource_type=gpu_model,
                provider="akash",
                source_connector="akash",
                source_role="direct",
                measurement_kind="availability_pressure",
                measurement_scope="gpu_model_units",
                unit="gpu_units",
                total_units=model_total,
                rented_units=None,
                available_units=model_available,
                pending_units=None,
                rented_share=None,
                available_share=_share(model_available, model_total),
                stock_status=_availability_label(model_available, model_total),
                count_precision="reported_counts",
                numerator_definition="GPU units currently reported available for this Akash model.",
                denominator_definition="Total GPU units reported for this Akash model.",
                source_url=AKASH_GPU_PRICES_URL,
                raw_ref=raw_ref,
                notes="Model availability does not identify how unavailable units split between active and pending.",
            )
        )
    return rows


def normalize_clore_market_state(
    servers: Iterable[Mapping[str, Any]],
    *,
    observed_at: datetime,
    raw_ref: str | None,
) -> list[ComputeMarketState]:
    """Build server-weighted on-demand rental occupancy from Clore."""
    groups: dict[str, list[bool]] = defaultdict(list)
    for server in servers:
        rented = server.get("rented")
        if not isinstance(rented, bool):
            continue
        groups["ALL_GPU"].append(rented)
        gpu_model = _clore_gpu_model(server)
        if gpu_model:
            groups[gpu_model].append(rented)

    rows = []
    for resource_type, states in sorted(groups.items()):
        total = float(len(states))
        rented = float(sum(states))
        available = total - rented
        rows.append(
            _state(
                observed_at=observed_at,
                resource_type=resource_type,
                provider="clore",
                source_connector="clore",
                source_role="direct",
                measurement_kind="rental_occupancy",
                measurement_scope="public_marketplace_on_demand_servers",
                unit="servers",
                total_units=total,
                rented_units=rented,
                available_units=available,
                pending_units=None,
                rented_share=_share(rented, total),
                available_share=_share(available, total),
                stock_status=None,
                count_precision="derived_from_reported_boolean",
                numerator_definition="Public marketplace servers whose on-demand rented flag is true.",
                denominator_definition="Public marketplace servers with a reported on-demand rented flag.",
                source_url=CLORE_MARKETPLACE_URL,
                raw_ref=raw_ref,
                notes="Server-weighted and on-demand only; active spot offers are not included in the numerator.",
            )
        )
    return rows


def normalize_prime_market_state(
    items: Iterable[Mapping[str, Any]],
    *,
    observed_at: datetime,
    raw_ref: str | None,
) -> list[ComputeMarketState]:
    """Build upstream-preserving availability observations from Prime."""
    groups: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for item in items:
        gpu_name = str(item.get("gpuType") or "").strip()
        gpu_memory = _float_or_none(item.get("gpuMemory"))
        gpu_model = canonical_gpu_model(
            gpu_name,
            gpu_memory * 1024 if gpu_memory is not None else None,
        )
        if not gpu_model:
            continue
        provider = canonical_provider_id(str(item.get("provider") or ""))
        groups[(provider, gpu_model)].append(item)

    rows = []
    for (provider, gpu_model), group in sorted(groups.items()):
        statuses = [str(item.get("stockStatus") or "").strip() for item in group]
        available_count = sum(_stock_available(status) for status in statuses)
        rows.append(
            _state(
                observed_at=observed_at,
                resource_type=gpu_model,
                provider=provider,
                source_connector="prime_intellect",
                source_role="aggregator",
                measurement_kind="availability_pressure",
                measurement_scope="upstream_listed_configurations",
                unit="configurations",
                total_units=None,
                rented_units=None,
                available_units=float(available_count),
                pending_units=None,
                rented_share=None,
                available_share=None,
                stock_status=_tightest_stock_status(statuses),
                count_precision="configuration_count",
                numerator_definition="Prime configurations currently carrying an available stock status.",
                denominator_definition="No total upstream fleet denominator is exposed by this endpoint.",
                source_url=PRIME_AVAILABILITY_URL,
                raw_ref=raw_ref,
                notes="Prime is an aggregator. Provider identifies the upstream supply source, not Prime itself.",
            )
        )
    return rows


def normalize_runpod_market_state(
    gpu_types: Iterable[Mapping[str, Any]],
    *,
    observed_at: datetime,
    raw_ref: str | None,
) -> list[ComputeMarketState]:
    rows = []
    for entry in gpu_types:
        gpu_name = str(entry.get("displayName") or entry.get("id") or "").strip()
        vram_gb = _float_or_none(entry.get("memoryInGb"))
        gpu_model = canonical_gpu_model(
            gpu_name,
            vram_gb * 1024 if vram_gb is not None else None,
        )
        lowest = entry.get("lowestPrice")
        if not gpu_model or not isinstance(lowest, Mapping):
            continue
        status = str(lowest.get("stockStatus") or "").strip()
        bundle_sizes = lowest.get("availableGpuCounts")
        available_sizes = (
            [value for value in bundle_sizes if _float_or_none(value) is not None]
            if isinstance(bundle_sizes, list)
            else []
        )
        rows.append(
            _state(
                observed_at=observed_at,
                resource_type=gpu_model,
                provider="runpod",
                source_connector="runpod",
                source_role="direct",
                measurement_kind="availability_pressure",
                measurement_scope="deployable_bundle_sizes",
                unit="bundle_sizes",
                total_units=None,
                rented_units=None,
                available_units=float(len(available_sizes)),
                pending_units=None,
                rented_share=None,
                available_share=None,
                stock_status=status or "unknown",
                count_precision="categorical_stock_and_bundle_sizes",
                numerator_definition="GPU-count bundle sizes currently returned as deployable.",
                denominator_definition="RunPod does not expose total fleet GPU units in this response.",
                source_url=RUNPOD_GRAPHQL_URL,
                raw_ref=raw_ref,
                notes="Stock status and bundle sizes describe deployability, not rented share.",
            )
        )
    return rows


def normalize_hyperstack_market_state(
    stocks: Iterable[Mapping[str, Any]],
    *,
    observed_at: datetime,
    raw_ref: str | None,
) -> list[ComputeMarketState]:
    rows = []
    for stock in stocks:
        region = str(stock.get("region") or "").strip()
        models = stock.get("models")
        if not isinstance(models, list):
            continue
        for model in models:
            if not isinstance(model, Mapping):
                continue
            gpu_name = str(model.get("model") or "").strip()
            gpu_model = canonical_gpu_model(gpu_name)
            configurations = model.get("configurations")
            if not gpu_model or not isinstance(configurations, Mapping):
                continue
            deployable = []
            for key, value in configurations.items():
                gpu_count = _configuration_gpu_count(key)
                configuration_count = _float_or_none(value)
                if (
                    gpu_count is not None
                    and configuration_count is not None
                    and configuration_count > 0
                ):
                    deployable.append(gpu_count * configuration_count)
            if not deployable:
                continue
            lower_bound = max(deployable)
            rows.append(
                _state(
                    observed_at=observed_at,
                    resource_type=gpu_model,
                    provider="hyperstack",
                    source_connector="hyperstack",
                    source_role="direct",
                    measurement_kind="availability_pressure",
                    measurement_scope=f"region:{region or 'unknown'}",
                    unit="gpu_units_lower_bound",
                    total_units=None,
                    rented_units=None,
                    available_units=float(lower_bound),
                    pending_units=None,
                    rented_share=None,
                    available_share=None,
                    stock_status=str(model.get("available") or "available"),
                    count_precision="max_deployable_configuration_lower_bound",
                    numerator_definition="Largest currently deployable configuration count expressed in GPU units.",
                    denominator_definition="Hyperstack does not expose total fleet GPU units in this response.",
                    source_url=HYPERSTACK_STOCK_URL,
                    raw_ref=raw_ref,
                    notes="Configuration sizes may overlap, so counts are not summed.",
                )
            )
    return rows


def canonical_provider_id(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    return PROVIDER_ALIASES.get(normalized, normalized) or "prime_intellect"


def _state(
    *,
    observed_at: datetime,
    resource_type: str,
    provider: str,
    source_connector: str,
    source_role: str,
    measurement_kind: str,
    measurement_scope: str,
    unit: str,
    total_units: float | None,
    rented_units: float | None,
    available_units: float | None,
    pending_units: float | None,
    rented_share: float | None,
    available_share: float | None,
    stock_status: str | None,
    count_precision: str,
    numerator_definition: str,
    denominator_definition: str,
    source_url: str,
    raw_ref: str | None,
    notes: str | None,
) -> ComputeMarketState:
    identity = "|".join(
        [
            observed_at.isoformat(),
            provider,
            source_connector,
            resource_type,
            measurement_kind,
            measurement_scope,
            unit,
        ]
    )
    observation_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    return ComputeMarketState(
        observation_id=observation_id,
        observed_at=observed_at,
        resource_market="gpu",
        resource_type=resource_type,
        provider=provider,
        source_connector=source_connector,
        source_role=source_role,
        measurement_kind=measurement_kind,
        measurement_scope=measurement_scope,
        unit=unit,
        total_units=total_units,
        rented_units=rented_units,
        available_units=available_units,
        pending_units=pending_units,
        rented_share=rented_share,
        available_share=available_share,
        stock_status=stock_status,
        count_precision=count_precision,
        numerator_definition=numerator_definition,
        denominator_definition=denominator_definition,
        aggregation_eligible=True,
        aggregation_exclusion_reason=None,
        source_url=source_url,
        raw_ref=raw_ref,
        notes=notes,
    )


def _clore_gpu_model(server: Mapping[str, Any]) -> str | None:
    specs = server.get("specs") if isinstance(server.get("specs"), Mapping) else {}
    gpu_array = server.get("gpu_array")
    gpu_names = (
        [str(value).strip() for value in gpu_array if str(value).strip()]
        if isinstance(gpu_array, list)
        else []
    )
    raw_name = gpu_names[0] if gpu_names else str(specs.get("gpu") or "").strip()
    vram_gb = _float_or_none(specs.get("gpuram"))
    return canonical_gpu_model(
        raw_name,
        vram_gb * 1024 if vram_gb is not None else None,
    )


def _gib_value(value: Any) -> float | None:
    import re

    match = re.search(r"\d+(?:\.\d+)?", str(value or ""))
    return float(match.group()) if match else None


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _float_or_zero(value: Any) -> float:
    return _float_or_none(value) or 0.0


def _share(numerator: float, denominator: float) -> float | None:
    if denominator <= 0:
        return None
    return max(0.0, min(1.0, numerator / denominator))


def _availability_label(available: float, total: float) -> str:
    share = _share(available, total) or 0.0
    if available <= 0:
        return "none"
    if share < 0.1:
        return "low"
    if share < 0.35:
        return "medium"
    return "high"


def _stock_available(status: str) -> int:
    return int(status.strip().lower() not in {"", "none", "unavailable"})


def _tightest_stock_status(statuses: Iterable[str]) -> str:
    order = {"none": 0, "unavailable": 0, "low": 1, "medium": 2, "high": 3}
    normalized = [status.strip().lower() for status in statuses if status.strip()]
    if not normalized:
        return "unknown"
    return min(normalized, key=lambda status: order.get(status, 2))


def _configuration_gpu_count(value: Any) -> float | None:
    text = str(value or "").strip().lower()
    if not text.endswith("x"):
        return None
    return _float_or_none(text[:-1])
