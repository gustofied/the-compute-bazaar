"""Prime frontier-GPU offer history, lifecycle events, and shelf SQL."""

from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .gold_models import gold_model_sql


PRIME_FRONTIER_METHODOLOGY = "prime_provider_floor_median"
PRIME_FRONTIER_SCOPE = "prime_secure_ondemand_frontier_all_shapes"
PRIME_FRONTIER_PRICE_INCREMENT = 0.25
PRIME_FRONTIER_SOURCE_URL = (
    "https://app.primeintellect.ai/dashboard/on-demand-gpus"
    "?image=ubuntu_22_cuda_12&security=Cheapest&pricing_type=Cheapest"
    "&location=Cheapest"
)
PRIME_FRONTIER_API_DOCS_URL = (
    "https://docs.primeintellect.ai/api-reference/check-gpu-availability"
)
PRIME_FRONTIER_PROVISION_DOCS_URL = (
    "https://docs.primeintellect.ai/api-reference/provision-gpu"
)


@dataclass(frozen=True)
class PrimeFrontierProduct:
    family_id: str
    label: str
    canonical_model: str
    api_gpu_type: str

    @property
    def market_url(self) -> str:
        return f"{PRIME_FRONTIER_SOURCE_URL}&gpu_type={self.api_gpu_type}&quantity=1"


PRIME_FRONTIER_PRODUCTS = (
    PrimeFrontierProduct("H100", "H100", "H100_80GB", "H100_80GB"),
    PrimeFrontierProduct("H200", "H200", "H200_141GB", "H200_141GB"),
    PrimeFrontierProduct("B200", "B200", "B200_180GB", "B200_180GB"),
    PrimeFrontierProduct("B300", "B300", "B300_288GB", "B300_262GB"),
)
PRIME_FRONTIER_PRODUCT_BY_FAMILY = {
    product.family_id: product for product in PRIME_FRONTIER_PRODUCTS
}

PRIME_FRONTIER_HISTORY_COLUMNS = (
    "listing_id",
    "provider_id",
    "provider",
    "source_offer_id",
    "gpu_family_id",
    "gpu_product_id",
    "gpu_model",
    "gpu_raw_name",
    "source_connector",
    "gpu_count",
    "available_gpu_count_lower_bound",
    "vram_gb",
    "price_usd_instance_hr",
    "price_usd_gpu_hr",
    "currency",
    "country",
    "region",
    "region_id",
    "is_spot",
    "is_secure",
    "source_availability_status",
    "gpu_socket",
    "source_stock_status",
    "price_is_variable",
    "minimum_executable_price_usd_instance_hr",
    "required_resource_price_usd_instance_hr",
    "price_basis",
    "observed_at",
    "raw_ref",
    "has_raw_evidence",
    "source_run_id",
    "source_manifest_ref",
    "source_normalized_ref",
    "calculated_at",
    "gold_run_id",
    "gold_observed_at",
    "gold_observed_date",
)


def prime_frontier_product_for_model(
    gpu_model: Any,
) -> PrimeFrontierProduct | None:
    model = str(gpu_model or "")
    for product in PRIME_FRONTIER_PRODUCTS:
        if model == product.canonical_model or model.startswith(
            f"{product.canonical_model}_x"
        ):
            return product
    return None


def normalize_prime_frontier_history(
    rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Transform retained Prime observations into the current Gold contract."""
    normalized: list[dict[str, Any]] = []
    for source in rows:
        if str(source.get("source_connector") or "") != "prime_intellect":
            continue
        product = prime_frontier_product_for_model(source.get("gpu_model"))
        if product is None:
            continue
        row = {column: source.get(column) for column in PRIME_FRONTIER_HISTORY_COLUMNS}
        row["gpu_family_id"] = product.family_id
        row["source_connector"] = "prime_intellect"
        # Prime history comes from its public availability endpoint. Older
        # retained rows omitted this field, but their presence in the response
        # already means they were available at observation time.
        row["source_availability_status"] = (
            source.get("source_availability_status") or "available"
        )
        row["observed_at"] = _timestamp(source.get("observed_at"))
        row["price_basis"] = (
            source.get("price_basis") or "provider_reported_gpu_base_rate"
        )
        row["gold_observed_at"] = _timestamp(
            source.get("gold_observed_at")
            or source.get("calculated_at")
            or source.get("observed_at")
        )
        row["gold_observed_date"] = source.get("gold_observed_date") or _date_part(
            row["gold_observed_at"]
        )
        normalized.append(row)

    deduplicated = {
        (str(row.get("gold_run_id") or ""), str(row.get("listing_id") or "")): row
        for row in normalized
        if row.get("gold_run_id") and row.get("listing_id")
    }
    return sorted(
        deduplicated.values(),
        key=lambda row: (
            str(row.get("gold_observed_at") or ""),
            str(row.get("gold_run_id") or ""),
            str(row.get("gpu_family_id") or ""),
            str(row.get("provider") or ""),
            float(row.get("price_usd_gpu_hr") or math.inf),
            str(row.get("listing_id") or ""),
        ),
    )


def build_prime_frontier_offer_events(
    history_rows: Iterable[Mapping[str, Any]],
    *,
    snapshot_keys: Iterable[tuple[Any, str]] = (),
) -> list[dict[str, Any]]:
    """Classify observable configuration changes without inventing fills."""
    normalized = normalize_prime_frontier_history(history_rows)
    run_times: dict[str, str] = {}
    for row in normalized:
        observed_at, run_id = _snapshot_key(
            row.get("gold_observed_at"), row.get("gold_run_id")
        )
        if run_id:
            run_times[run_id] = max(run_times.get(run_id, ""), observed_at)
    for observed_at, run_id in snapshot_keys:
        timestamp, normalized_run_id = _snapshot_key(observed_at, run_id)
        if normalized_run_id:
            run_times[normalized_run_id] = timestamp

    run_keys = sorted((observed_at, run_id) for run_id, observed_at in run_times.items())
    snapshots: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in normalized:
        snapshots[
            (
                str(row.get("gpu_family_id") or ""),
                str(row.get("gold_run_id") or ""),
            )
        ].append(row)

    events: list[dict[str, Any]] = []
    for product in PRIME_FRONTIER_PRODUCTS:
        previous_key: tuple[str, str] | None = None
        previous_rows: dict[str, dict[str, Any]] = {}
        for observed_at, run_id in run_keys:
            snapshot_rows = snapshots.get((product.family_id, run_id), [])
            current_rows = {
                str(row["listing_id"]): row
                for row in snapshot_rows
                if _is_eligible_offer(row)
            }
            previous_observed_at = previous_key[0] if previous_key else None
            previous_run_id = previous_key[1] if previous_key else None
            comparison_gap_seconds = _seconds_between(previous_observed_at, observed_at)
            identities = sorted(set(previous_rows) | set(current_rows))
            for listing_id in identities:
                previous = previous_rows.get(listing_id)
                current = current_rows.get(listing_id)
                event_type = _event_type(previous, current)
                before = _float_or_none(
                    previous.get("price_usd_gpu_hr") if previous else None
                )
                after = _float_or_none(
                    current.get("price_usd_gpu_hr") if current else None
                )
                active = current or previous
                if active is None:
                    continue
                event_price = after if after is not None else before
                delta = (
                    after - before if before is not None and after is not None else None
                )
                delta_pct = (
                    delta / before
                    if delta is not None and before not in {None, 0}
                    else None
                )
                event_id = hashlib.sha256(
                    (f"{run_id}|{product.family_id}|{listing_id}|{event_type}").encode(
                        "utf-8"
                    )
                ).hexdigest()[:24]
                events.append(
                    {
                        "event_id": event_id,
                        "event_type": event_type,
                        "event_label": _event_label(event_type),
                        "listing_id": listing_id,
                        "provider": active.get("provider"),
                        "source_connector": "prime_intellect",
                        "gpu_family_id": product.family_id,
                        "gpu_model": active.get("gpu_model"),
                        "gpu_count": active.get("gpu_count"),
                        "gpu_socket": active.get("gpu_socket"),
                        "region": active.get("region"),
                        "stock_status_before": (
                            previous.get("source_stock_status") if previous else None
                        ),
                        "stock_status_after": (
                            current.get("source_stock_status") if current else None
                        ),
                        "price_before_usd_gpu_hr": before,
                        "price_after_usd_gpu_hr": after,
                        "price_delta_usd_gpu_hr": delta,
                        "price_delta_fraction": delta_pct,
                        "price_level_usd_gpu_hr": (
                            _price_level(event_price)
                            if event_price is not None
                            else None
                        ),
                        "previous_observed_at": previous_observed_at,
                        "observed_at": observed_at,
                        "comparison_gap_seconds": comparison_gap_seconds,
                        "previous_gold_run_id": previous_run_id,
                        "gold_run_id": run_id,
                        "methodology": PRIME_FRONTIER_METHODOLOGY,
                        "source_url": product.market_url,
                        "notes": (
                            "Observable availability event; leaving public "
                            "availability is not evidence of a rental, fill, "
                            "or cancellation."
                        ),
                    }
                )
            previous_rows = current_rows
            previous_key = (observed_at, run_id)
    return events


def _snapshot_key(observed_at: Any, run_id: Any) -> tuple[str, str]:
    timestamp = _timestamp(observed_at)
    return (timestamp.isoformat() if timestamp else "", str(run_id or ""))


def prime_frontier_reference_history_sql() -> str:
    """Render the provider-balanced Prime reference Gold model."""
    return gold_model_sql(
        "fact_prime_frontier_offer_reference_history",
        {
            "reference_scope": PRIME_FRONTIER_SCOPE,
            "methodology_version": PRIME_FRONTIER_METHODOLOGY,
        },
    )


def prime_frontier_ladder_sql(*, current_gold_run_id: str) -> str:
    """Render the benchmark-centered Prime offer-level Gold model."""
    increment = PRIME_FRONTIER_PRICE_INCREMENT
    return gold_model_sql(
        "fact_prime_frontier_offer_ladder",
        {"current_gold_run_id": current_gold_run_id},
        fragments={
            "price_increment": str(increment),
            "half_price_increment": str(increment / 2),
        },
    )


def _is_eligible_offer(row: Mapping[str, Any]) -> bool:
    price = _float_or_none(row.get("price_usd_gpu_hr"))
    return bool(
        price is not None
        and price > 0
        and str(row.get("source_availability_status") or "") == "available"
        and row.get("is_spot") is not True
        and row.get("is_secure") is True
    )


def _event_type(
    previous: Mapping[str, Any] | None,
    current: Mapping[str, Any] | None,
) -> str:
    if previous is None:
        return "entered"
    if current is None:
        return "left_availability"
    before = _float_or_none(previous.get("price_usd_gpu_hr"))
    after = _float_or_none(current.get("price_usd_gpu_hr"))
    if (
        before is not None
        and after is not None
        and not math.isclose(before, after, rel_tol=1e-9, abs_tol=1e-9)
    ):
        return "repriced_up" if after > before else "repriced_down"
    if str(previous.get("source_stock_status") or "") != str(
        current.get("source_stock_status") or ""
    ):
        return "stock_status_changed"
    return "remained"


def _event_label(event_type: str) -> str:
    return {
        "entered": "Entered availability",
        "left_availability": "Left availability",
        "repriced_up": "Repriced higher",
        "repriced_down": "Repriced lower",
        "stock_status_changed": "Stock label changed",
        "remained": "Remained available",
    }[event_type]


def _price_level(value: float) -> float:
    return (
        math.floor(value / PRIME_FRONTIER_PRICE_INCREMENT + 0.5)
        * PRIME_FRONTIER_PRICE_INCREMENT
    )


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _date_part(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)[:10] or None


def _timestamp(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _seconds_between(start: Any, end: Any) -> float | None:
    if not start or not end:
        return None
    try:
        left = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        right = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (right - left).total_seconds()
