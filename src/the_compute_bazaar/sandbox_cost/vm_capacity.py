"""Refresh a fixed public VM-capacity cohort into bronze and silver."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlencode

import requests

from the_compute_bazaar.prices.providers.ecb import fetch_latest_eur_usd_rate
from the_compute_bazaar.prices.providers.http import retrying_session
from the_compute_bazaar.prices.storage import (
    exclusive_lease,
    read_optional_json,
    read_parquet_rows,
    write_bytes,
    write_json,
    write_parquet_rows,
)


VM_CAPACITY_COHORT_ID = "public_vm_4vcpu_8gib_v1"
VM_CAPACITY_METHODOLOGY = "fixed_exact_shape_observed_offer_median_iqr_v1"
VM_TARGET_SHAPE = {"vcpus": 4, "memory_gib": 8}
VM_PROVIDER_ORDER = ("linode", "vultr", "scaleway", "azure")

LINODE_URL = "https://api.linode.com/v4/linode/types"
VULTR_URL = "https://api.vultr.com/v2/plans"
SCALEWAY_URL = (
    "https://api.scaleway.com/product-catalog/v2alpha1/public-catalog/products"
)
AZURE_URL = "https://prices.azure.com/api/retail/prices"

LINODE_PLAN_ID = "g6-standard-4"
VULTR_PLAN_ID = "vc2-4c-8gb"
SCALEWAY_SKU = "/compute/basic3_x4c_8g/run_fr-par-2"
AZURE_SKU = "Standard_F4s_v2"

AZURE_FILTER = (
    "serviceName eq 'Virtual Machines' and "
    "armSkuName eq 'Standard_F4s_v2' and "
    "armRegionName eq 'westeurope' and "
    "priceType eq 'Consumption'"
)

PROVIDER_LABELS = {
    "linode": "Akamai Linode",
    "vultr": "Vultr",
    "scaleway": "Scaleway",
    "azure": "Microsoft Azure",
}

PROVIDER_COLORS = {
    "linode": "#466f73",
    "vultr": "#53789f",
    "scaleway": "#6f6091",
    "azure": "#5f7d98",
}

PROVIDER_SOURCE_URLS = {
    "linode": "https://techdocs.akamai.com/linode-api/reference/get-linode-types",
    "vultr": "https://docs.vultr.com/reference/vultr-cli/plans/list",
    "scaleway": (
        "https://www.scaleway.com/en/developers/api/product-catalog/public-catalog"
    ),
    "azure": (
        "https://learn.microsoft.com/en-us/rest/api/"
        "cost-management/retail-prices/azure-retail-prices"
    ),
}

PROVIDER_SPEC_URLS = {
    "linode": "https://www.linode.com/pricing/",
    "vultr": "https://www.vultr.com/pricing/",
    "scaleway": "https://www.scaleway.com/en/pricing/",
    "azure": (
        "https://learn.microsoft.com/en-us/azure/virtual-machines/"
        "sizes/compute-optimized/fsv2-series"
    ),
}


@dataclass(frozen=True)
class VmCapacityRefresh:
    run_id: str
    checked_at: str
    status: str
    successful_providers: list[str]
    failed_providers: list[str]
    raw_refs: dict[str, list[str]]
    history_ref: str
    current_ref: str
    manifest_ref: str
    history_event_count: int
    current_member_count: int


@dataclass(frozen=True)
class _ProviderFetch:
    row: dict[str, Any]
    raw_payloads: list[tuple[str, bytes, str]]


class _ProviderSourceError(ValueError):
    """Carry fetched source bytes through parser/schema failures."""

    def __init__(
        self,
        error: Exception,
        raw_payloads: list[tuple[str, bytes, str]],
    ) -> None:
        super().__init__(str(error))
        self.original_error_type = type(error).__name__
        self.raw_payloads = raw_payloads


def refresh_vm_capacity_sources(
    *,
    output_root: str = "data/sandbox-cost",
    raw_root: str = "data/raw",
    observed_at: datetime | str | None = None,
    session: requests.Session | None = None,
) -> VmCapacityRefresh:
    """Check exact public VM offers and preserve raw plus hourly observations."""
    lease_ref = _join(output_root, "_locks/vm-capacity-refresh.json")
    with exclusive_lease(lease_ref):
        return _refresh_vm_capacity_sources_unlocked(
            output_root=output_root,
            raw_root=raw_root,
            observed_at=observed_at,
            session=session,
        )


def _refresh_vm_capacity_sources_unlocked(
    *,
    output_root: str,
    raw_root: str,
    observed_at: datetime | str | None,
    session: requests.Session | None,
) -> VmCapacityRefresh:
    checked = _coerce_utc(observed_at)
    checked_at = checked.isoformat()
    checked_date = checked.date().isoformat()
    run_id = f"vm-capacity-{checked.strftime('%Y%m%dT%H%M%SZ')}"
    client = session or retrying_session()

    state_refs = resolve_vm_capacity_state_refs(output_root)
    state_manifest = read_optional_json(state_refs["manifest_ref"])
    history_ref = state_refs["history_ref"]
    current_ref = state_refs["current_ref"]
    history = _read_optional_parquet(history_ref)
    current_by_provider = {
        str(row["provider_id"]): dict(row)
        for row in _read_optional_parquet(current_ref)
    }

    successful: list[str] = []
    failed: list[str] = []
    errors: dict[str, dict[str, str]] = {}
    raw_refs: dict[str, list[str]] = {}
    source_checks: dict[str, dict[str, Any]] = {}
    fetchers: dict[str, Callable[[requests.Session], _ProviderFetch]] = {
        "linode": _fetch_linode,
        "vultr": _fetch_vultr,
        "scaleway": _fetch_scaleway,
        "azure": _fetch_azure,
    }

    for provider_id in VM_PROVIDER_ORDER:
        try:
            result = fetchers[provider_id](client)
            row = {
                **result.row,
                "provider_id": provider_id,
                "provider_label": PROVIDER_LABELS[provider_id],
                "series_order": VM_PROVIDER_ORDER.index(provider_id) + 1,
                "cohort_id": VM_CAPACITY_COHORT_ID,
                "methodology_version": VM_CAPACITY_METHODOLOGY,
                "target_vcpus": VM_TARGET_SHAPE["vcpus"],
                "target_memory_gib": VM_TARGET_SHAPE["memory_gib"],
                "checked_at": checked_at,
                "source_url": PROVIDER_SOURCE_URLS[provider_id],
                "spec_url": PROVIDER_SPEC_URLS[provider_id],
                "color": PROVIDER_COLORS[provider_id],
            }
            _validate_normalized_row(row)
            row["observation_fingerprint"] = _observation_fingerprint(row)

            previous = current_by_provider.get(provider_id)
            existing_snapshot = next(
                (
                    item
                    for item in history
                    if item["provider_id"] == provider_id
                    and str(item["checked_at"]) == checked_at
                ),
                None,
            )
            if existing_snapshot is not None:
                if (
                    existing_snapshot.get("observation_fingerprint")
                    != row["observation_fingerprint"]
                ):
                    raise ValueError(
                        f"Conflicting immutable {provider_id} snapshot at {checked_at}"
                    )
                row = dict(existing_snapshot)
                provider_raw_refs = json.loads(str(row["raw_refs_json"]))
            else:
                provider_raw_refs = _write_raw_payloads(
                    raw_root=raw_root,
                    provider_id=provider_id,
                    observed_date=checked_date,
                    run_id=run_id,
                    retrieved_at=checked_at,
                    payloads=result.raw_payloads,
                )
                raw_refs[provider_id] = provider_raw_refs
                row["raw_refs_json"] = json.dumps(
                    provider_raw_refs,
                    separators=(",", ":"),
                )
                previous_event_order = max(
                    (
                        int(item["event_order"])
                        for item in history
                        if item["provider_id"] == provider_id
                    ),
                    default=0,
                )
                row["first_observed_at"] = checked_at
                row["last_observed_at"] = checked_at
                row["observation_count"] = (
                    int(previous["observation_count"]) + 1 if previous else 1
                )
                row["event_order"] = previous_event_order + 1
                history.append(dict(row))
            raw_refs[provider_id] = provider_raw_refs
            current_by_provider[provider_id] = row
            successful.append(provider_id)
            source_checks[provider_id] = {
                "status": "ok",
                "plan_id": row["plan_id"],
                "price_usd_per_hour": row["price_usd_per_hour"],
                "raw_refs": provider_raw_refs,
                "observation_fingerprint": row["observation_fingerprint"],
            }
        except Exception as exc:  # noqa: BLE001 - sources are isolated.
            provider_raw_refs: list[str] = []
            raw_capture_error: str | None = None
            if isinstance(exc, _ProviderSourceError) and exc.raw_payloads:
                try:
                    provider_raw_refs = _write_raw_payloads(
                        raw_root=raw_root,
                        provider_id=provider_id,
                        observed_date=checked_date,
                        run_id=run_id,
                        retrieved_at=checked_at,
                        payloads=exc.raw_payloads,
                    )
                    raw_refs[provider_id] = provider_raw_refs
                except Exception as capture_exc:  # noqa: BLE001
                    raw_capture_error = str(capture_exc)
            failed.append(provider_id)
            errors[provider_id] = {
                "error_type": (
                    exc.original_error_type
                    if isinstance(exc, _ProviderSourceError)
                    else type(exc).__name__
                ),
                "message": str(exc),
            }
            if raw_capture_error:
                errors[provider_id]["raw_capture_error"] = raw_capture_error
            source_checks[provider_id] = {
                "status": "error",
                **errors[provider_id],
                "raw_refs": provider_raw_refs,
            }

    if str(state_manifest.get("run_id") or "") == run_id:
        current_members = {
            str(row["provider_id"])
            for row in current_by_provider.values()
            if row["cohort_id"] == VM_CAPACITY_COHORT_ID
        }
        return VmCapacityRefresh(
            run_id=run_id,
            checked_at=checked_at,
            status="warning" if failed else str(state_manifest.get("status") or "ok"),
            successful_providers=successful,
            failed_providers=failed,
            raw_refs=raw_refs,
            history_ref=history_ref,
            current_ref=current_ref,
            manifest_ref=state_refs["manifest_ref"],
            history_event_count=len(history),
            current_member_count=len(current_members),
        )

    history = repair_observation_history(history, key="provider_id")
    current_by_provider = latest_observation_rows(history, key="provider_id")
    current = sorted(
        current_by_provider.values(),
        key=lambda row: int(row["series_order"]),
    )
    _validate_history(history)
    generation_prefix = _join(
        output_root,
        f"silver/vm_capacity/generations/run_id={run_id}",
    )
    history_ref = _join(generation_prefix, "offer_history.parquet")
    current_ref = _join(generation_prefix, "current.parquet")
    manifest_ref = _join(generation_prefix, "manifest.json")
    write_parquet_rows(history_ref, history)
    write_parquet_rows(current_ref, current)

    current_members = {
        str(row["provider_id"])
        for row in current
        if row["cohort_id"] == VM_CAPACITY_COHORT_ID
    }
    complete = current_members == set(VM_PROVIDER_ORDER)
    status = "ok" if not failed and complete else "warning"
    manifest = {
        "manifest_version": "vm_capacity_source_manifest_v1",
        "manifest_ref": manifest_ref,
        "run_id": run_id,
        "checked_at": checked_at,
        "status": status,
        "cohort_id": VM_CAPACITY_COHORT_ID,
        "methodology_version": VM_CAPACITY_METHODOLOGY,
        "target_shape": VM_TARGET_SHAPE,
        "fixed_members": list(VM_PROVIDER_ORDER),
        "successful_providers": successful,
        "failed_providers": failed,
        "errors": errors,
        "source_checks": source_checks,
        "raw_refs": raw_refs,
        "history_ref": history_ref,
        "current_ref": current_ref,
        "history_event_count": len(history),
        "history_observation_count": len(history),
        "current_member_count": len(current_members),
        "cohort_complete": complete,
        "source_notes": {
            "storage": (
                "Storage treatment differs by offer and remains explicit in "
                "each normalized row."
            ),
            "currency": (
                "Scaleway EUR is converted with the latest ECB EUR/USD "
                "reference rate; FX changes can change the USD observation."
            ),
            "history": (
                "Raw and normalized source snapshots are retained every run, "
                "including unchanged rates, so gold can publish a continuous "
                "hourly series."
            ),
        },
    }
    write_json(manifest_ref, manifest)
    write_json(_vm_capacity_latest_manifest_ref(output_root), manifest)
    return VmCapacityRefresh(
        run_id=run_id,
        checked_at=checked_at,
        status=status,
        successful_providers=successful,
        failed_providers=failed,
        raw_refs=raw_refs,
        history_ref=history_ref,
        current_ref=current_ref,
        manifest_ref=manifest_ref,
        history_event_count=len(history),
        current_member_count=len(current_members),
    )


def validate_vm_capacity_history(
    *,
    history_ref: str,
    current_ref: str,
) -> dict[str, Any]:
    """Validate retained VM events and the latest exact-shape cross-section."""
    history = read_parquet_rows(history_ref)
    current = read_parquet_rows(current_ref)
    _validate_history(history)
    for row in current:
        _validate_normalized_row(row)
    current_ids = {str(row["provider_id"]) for row in current}
    unknown = current_ids - set(VM_PROVIDER_ORDER)
    if unknown:
        raise ValueError(f"Unknown VM-capacity providers: {sorted(unknown)}")
    return {
        "history_event_count": len(history),
        "history_observation_count": len(history),
        "current_member_count": len(current_ids),
        "cohort_complete": current_ids == set(VM_PROVIDER_ORDER),
    }


def resolve_vm_capacity_state_refs(output_root: str) -> dict[str, str]:
    """Resolve the latest immutable VM-capacity generation, with legacy fallback."""
    latest_ref = _vm_capacity_latest_manifest_ref(output_root)
    latest = read_optional_json(latest_ref)
    if latest.get("history_ref") and latest.get("current_ref"):
        return {
            "history_ref": str(latest["history_ref"]),
            "current_ref": str(latest["current_ref"]),
            "manifest_ref": str(latest.get("manifest_ref") or latest_ref),
        }
    return {
        "history_ref": _join(
            output_root,
            "silver/vm_capacity_offer_history.parquet",
        ),
        "current_ref": _join(
            output_root,
            "silver/vm_capacity_current.parquet",
        ),
        "manifest_ref": _join(
            output_root,
            "silver/vm_capacity_source_manifest.json",
        ),
    }


def _fetch_linode(session: requests.Session) -> _ProviderFetch:
    headers = {
        "Accept": "application/json",
        "User-Agent": "the-compute-bazaar/0.1",
        "X-Filter": json.dumps({"id": LINODE_PLAN_ID}, separators=(",", ":")),
    }
    response = session.get(
        LINODE_URL,
        params={"page_size": 100},
        headers=headers,
        timeout=60,
    )
    raw_payloads = [
        ("linode-types.json", response.content, "application/json"),
    ]
    try:
        response.raise_for_status()
        payload = response.json()
        rows = _require_list(payload, "data", "Linode")
        plan = _exact_one(
            rows,
            lambda row: row.get("id") == LINODE_PLAN_ID,
            "Linode",
        )
        if (
            int(plan.get("vcpus") or 0) != 4
            or int(plan.get("memory") or 0) != 8192
            or str(plan.get("class")) != "standard"
            or int(plan.get("gpus") or 0) != 0
        ):
            raise ValueError(f"Linode {LINODE_PLAN_ID} machine shape drifted")
        hourly = _positive_number(
            (plan.get("price") or {}).get("hourly"),
            "Linode price",
        )
        disk_gb = _positive_number(plan.get("disk"), "Linode disk MB") / 1024
        row = _base_row(
            plan_id=LINODE_PLAN_ID,
            plan_label=str(plan.get("label") or LINODE_PLAN_ID),
            price=hourly,
            currency="USD",
            region_id="global-base",
            region_label="Base public price",
            storage_gb=disk_gb,
            storage_type="bundled local storage",
            storage_included=True,
            storage_scope="advertised plan disk included",
            cpu_model="not stated",
            tenancy="shared vCPU",
            price_effective_at=None,
        )
        return _ProviderFetch(row=row, raw_payloads=raw_payloads)
    except Exception as exc:
        raise _ProviderSourceError(exc, raw_payloads) from exc


def _fetch_vultr(session: requests.Session) -> _ProviderFetch:
    response = session.get(
        VULTR_URL,
        params={"per_page": 500, "type": "vc2"},
        headers={
            "Accept": "application/json",
            "User-Agent": "the-compute-bazaar/0.1",
        },
        timeout=60,
    )
    raw_payloads = [
        ("vultr-plans.json", response.content, "application/json"),
    ]
    try:
        response.raise_for_status()
        payload = response.json()
        rows = _require_list(payload, "plans", "Vultr")
        plan = _exact_one(
            rows,
            lambda row: row.get("id") == VULTR_PLAN_ID,
            "Vultr",
        )
        if (
            int(plan.get("vcpu_count") or 0) != 4
            or int(plan.get("ram") or 0) != 8192
            or str(plan.get("type")) != "vc2"
            or str(plan.get("gpu_brand") or "none").lower() not in {"", "none"}
        ):
            raise ValueError(f"Vultr {VULTR_PLAN_ID} machine shape drifted")
        locations = {str(value) for value in plan.get("locations") or []}
        reference_region = "cdg" if "cdg" in locations else "fra"
        if reference_region not in locations:
            raise ValueError(f"Vultr {VULTR_PLAN_ID} is unavailable in cdg or fra")
        hourly = _positive_number(plan.get("hourly_cost"), "Vultr price")
        disk_gb = _positive_number(plan.get("disk"), "Vultr disk GB")
        row = _base_row(
            plan_id=VULTR_PLAN_ID,
            plan_label=str(plan.get("id") or VULTR_PLAN_ID),
            price=hourly,
            currency="USD",
            region_id=reference_region,
            region_label="Paris" if reference_region == "cdg" else "Frankfurt",
            storage_gb=disk_gb,
            storage_type="bundled SSD",
            storage_included=True,
            storage_scope="advertised plan SSD included",
            cpu_model=str(plan.get("cpu_vendor") or "not stated"),
            tenancy="shared vCPU thread",
            price_effective_at=None,
        )
        return _ProviderFetch(row=row, raw_payloads=raw_payloads)
    except Exception as exc:
        raise _ProviderSourceError(exc, raw_payloads) from exc


def _fetch_scaleway(session: requests.Session) -> _ProviderFetch:
    raw_payloads: list[tuple[str, bytes, str]] = []
    try:
        target: Mapping[str, Any] | None = None
        page = 1
        page_size = 100
        total_count: int | None = None
        while page <= 100:
            response = session.get(
                SCALEWAY_URL,
                params={"page": page, "page_size": page_size},
                headers={
                    "Accept": "application/json",
                    "User-Agent": "the-compute-bazaar/0.1",
                },
                timeout=60,
            )
            raw_payloads.append(
                (
                    f"scaleway-products-page-{page:03d}.json",
                    response.content,
                    "application/json",
                )
            )
            response.raise_for_status()
            payload = response.json()
            rows = _require_list(payload, "products", "Scaleway")
            matches = [row for row in rows if row.get("sku") == SCALEWAY_SKU]
            if len(matches) > 1:
                raise ValueError(f"Scaleway returned duplicate SKU {SCALEWAY_SKU}")
            if matches:
                target = matches[0]
                break
            total_count = int(payload.get("total_count") or 0)
            if not rows or page * page_size >= total_count:
                break
            page += 1
        if target is None:
            raise ValueError(f"Scaleway did not return exact SKU {SCALEWAY_SKU}")

        properties = target.get("properties") or {}
        hardware = properties.get("hardware") or {}
        cpu = hardware.get("cpu") or {}
        memory = hardware.get("ram") or hardware.get("memory") or {}
        cpu_count = int(
            cpu.get("virtual_cpu_count")
            or cpu.get("count")
            or (cpu.get("virtual") or {}).get("count")
            or 0
        )
        memory_bytes = int(memory.get("size") or memory.get("bytes") or 0)
        if cpu_count != 4 or memory_bytes != 8 * 1024**3:
            raise ValueError(f"Scaleway {SCALEWAY_SKU} machine shape drifted")
        unit = target.get("unit_of_measure") or {}
        if str(unit.get("unit")) != "hour" or int(unit.get("size") or 0) != 1:
            raise ValueError(f"Scaleway {SCALEWAY_SKU} billing unit drifted")
        native_price = _money_value(
            ((target.get("price") or {}).get("retail_price") or {}),
            expected_currency="EUR",
        )
        fx = fetch_latest_eur_usd_rate(session)
        raw_payloads.append(
            ("ecb-eur-usd.csv", fx.raw_payload.encode("utf-8"), "text/csv")
        )
        usd_price = native_price * Decimal(str(fx.rate))
        row = _base_row(
            plan_id=SCALEWAY_SKU,
            plan_label=str(target.get("product") or "BASIC3-X4C-8G"),
            price=float(usd_price),
            currency="USD",
            source_currency="EUR",
            source_price=float(native_price),
            fx_rate=fx.rate,
            fx_observed_date=fx.observed_date,
            region_id="fr-par-2",
            region_label="Paris 2",
            storage_gb=None,
            storage_type="block storage",
            storage_included=False,
            storage_scope="persistent block storage priced separately",
            cpu_model=str(cpu.get("description") or cpu.get("type") or "not stated"),
            tenancy="shared vCPU",
            price_effective_at=None,
        )
        return _ProviderFetch(row=row, raw_payloads=raw_payloads)
    except Exception as exc:
        raise _ProviderSourceError(exc, raw_payloads) from exc


def _fetch_azure(session: requests.Session) -> _ProviderFetch:
    response = session.get(
        AZURE_URL,
        params={"currencyCode": "USD", "$filter": AZURE_FILTER},
        headers={
            "Accept": "application/json",
            "User-Agent": "the-compute-bazaar/0.1",
        },
        timeout=60,
    )
    query = urlencode({"currencyCode": "USD", "$filter": AZURE_FILTER})
    raw_payloads = [
        ("azure-retail-price.json", response.content, "application/json"),
        (
            "request-url.txt",
            f"{AZURE_URL}?{query}\n".encode("utf-8"),
            "text/plain",
        ),
    ]
    try:
        response.raise_for_status()
        payload = response.json()
        rows = _require_list(payload, "Items", "Azure")
        plan = _exact_one(
            rows,
            lambda row: (
                row.get("armSkuName") == AZURE_SKU
                and row.get("armRegionName") == "westeurope"
                and row.get("skuName") == "F4s v2"
                and row.get("productName") == "Virtual Machines FSv2 Series"
                and row.get("type") == "Consumption"
                and row.get("unitOfMeasure") == "1 Hour"
            ),
            "Azure",
        )
        hourly = _positive_number(plan.get("retailPrice"), "Azure price")
        row = _base_row(
            plan_id=AZURE_SKU,
            plan_label="Standard F4s v2",
            price=hourly,
            currency="USD",
            region_id="westeurope",
            region_label=str(plan.get("location") or "West Europe"),
            storage_gb=32,
            storage_type="temporary local disk",
            storage_included=True,
            storage_scope=("32 GiB temporary disk; OS and persistent disks separate"),
            cpu_model="Intel Xeon Platinum 8272CL or 8168",
            tenancy="shared virtual machine",
            price_effective_at=str(plan.get("effectiveStartDate") or "") or None,
        )
        row["source_meter_id"] = str(plan.get("meterId") or "")
        row["source_sku_id"] = str(plan.get("skuId") or "")
        return _ProviderFetch(row=row, raw_payloads=raw_payloads)
    except Exception as exc:
        raise _ProviderSourceError(exc, raw_payloads) from exc


def _base_row(
    *,
    plan_id: str,
    plan_label: str,
    price: float,
    currency: str,
    region_id: str,
    region_label: str,
    storage_gb: float | None,
    storage_type: str,
    storage_included: bool,
    storage_scope: str,
    cpu_model: str,
    tenancy: str,
    price_effective_at: str | None,
    source_currency: str | None = None,
    source_price: float | None = None,
    fx_rate: float | None = None,
    fx_observed_date: str | None = None,
) -> dict[str, Any]:
    return {
        "plan_id": plan_id,
        "plan_label": plan_label,
        "price_usd_per_hour": float(price),
        "currency": currency,
        "source_price_per_hour": float(
            source_price if source_price is not None else price
        ),
        "source_currency": source_currency or currency,
        "fx_rate_usd_per_source_currency": fx_rate if fx_rate is not None else 1.0,
        "fx_observed_date": fx_observed_date,
        "vcpus": 4,
        "memory_gib": 8,
        "region_id": region_id,
        "region_label": region_label,
        "storage_gb": float(storage_gb) if storage_gb is not None else None,
        "storage_type": storage_type,
        "storage_included": storage_included,
        "storage_scope": storage_scope,
        "cpu_model": cpu_model,
        "tenancy": tenancy,
        "billing_mode": "linux on-demand public offer",
        "price_effective_at": price_effective_at,
    }


def _write_raw_payloads(
    *,
    raw_root: str,
    provider_id: str,
    observed_date: str,
    run_id: str,
    retrieved_at: str,
    payloads: list[tuple[str, bytes, str]],
) -> list[str]:
    refs: list[str] = []
    files: list[dict[str, Any]] = []
    prefix = _join(
        raw_root,
        (
            "sandbox-cost/vm-capacity/"
            f"provider={provider_id}/date={observed_date}/run_id={run_id}"
        ),
    )
    for filename, payload, content_type in payloads:
        ref = _join(prefix, filename)
        write_bytes(ref, payload, content_type=content_type)
        refs.append(ref)
        files.append(
            {
                "path": ref,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "size_bytes": len(payload),
                "content_type": content_type,
            }
        )
    manifest_ref = _join(prefix, "manifest.json")
    write_json(
        manifest_ref,
        {
            "manifest_version": "vm_capacity_raw_capture_v1",
            "provider_id": provider_id,
            "run_id": run_id,
            "retrieved_at": retrieved_at,
            "files": files,
        },
    )
    refs.append(manifest_ref)
    return refs


def _validate_normalized_row(row: Mapping[str, Any]) -> None:
    required = (
        "provider_id",
        "plan_id",
        "price_usd_per_hour",
        "source_price_per_hour",
        "source_currency",
        "vcpus",
        "memory_gib",
        "region_id",
        "storage_included",
        "storage_scope",
        "cohort_id",
    )
    missing = [key for key in required if row.get(key) is None]
    if missing:
        raise ValueError(f"VM-capacity row is missing fields: {missing}")
    if int(row["vcpus"]) != 4 or float(row["memory_gib"]) != 8:
        raise ValueError(
            f"Incompatible VM shape for {row.get('provider_id')}: "
            f"{row.get('vcpus')} vCPU, {row.get('memory_gib')} GiB"
        )
    if str(row["cohort_id"]) != VM_CAPACITY_COHORT_ID:
        raise ValueError(f"Unexpected VM cohort {row['cohort_id']}")
    _positive_number(row["price_usd_per_hour"], "normalized VM price")


def _validate_history(rows: list[dict[str, Any]]) -> None:
    seen: set[tuple[str, int]] = set()
    snapshots: set[tuple[str, str]] = set()
    for row in rows:
        _validate_normalized_row(row)
        key = (str(row["provider_id"]), int(row["event_order"]))
        if key in seen:
            raise ValueError(f"Duplicate VM-capacity event {key}")
        seen.add(key)
        snapshot_key = (
            str(row["provider_id"]),
            str(row["checked_at"]),
        )
        if snapshot_key in snapshots:
            raise ValueError(
                "VM-capacity history repeats an hourly source snapshot for "
                f"{row['provider_id']} at {row['checked_at']}"
            )
        snapshots.add(snapshot_key)


def _observation_fingerprint(row: Mapping[str, Any]) -> str:
    fields = {
        key: row.get(key)
        for key in (
            "provider_id",
            "plan_id",
            "price_usd_per_hour",
            "currency",
            "source_price_per_hour",
            "source_currency",
            "fx_rate_usd_per_source_currency",
            "fx_observed_date",
            "vcpus",
            "memory_gib",
            "region_id",
            "storage_gb",
            "storage_type",
            "storage_included",
            "storage_scope",
            "cpu_model",
            "tenancy",
            "billing_mode",
            "price_effective_at",
            "cohort_id",
            "methodology_version",
        )
    }
    payload = json.dumps(fields, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _require_list(
    payload: Mapping[str, Any],
    key: str,
    provider: str,
) -> list[Mapping[str, Any]]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise ValueError(f"{provider} response schema drift: {key!r} is not a list")
    if not all(isinstance(row, Mapping) for row in value):
        raise ValueError(f"{provider} response schema drift: invalid row")
    return value


def _exact_one(
    rows: list[Mapping[str, Any]],
    predicate: Callable[[Mapping[str, Any]], bool],
    provider: str,
) -> Mapping[str, Any]:
    matches = [row for row in rows if predicate(row)]
    if len(matches) != 1:
        raise ValueError(f"{provider} exact plan match count was {len(matches)}, not 1")
    return matches[0]


def _positive_number(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} is not numeric") from exc
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{label} must be a finite positive number")
    return number


def _money_value(
    value: Mapping[str, Any],
    *,
    expected_currency: str,
) -> Decimal:
    if value.get("currency_code") != expected_currency:
        raise ValueError(
            f"Expected {expected_currency}, got {value.get('currency_code')}"
        )
    try:
        units = Decimal(str(value.get("units") or 0))
        nanos = Decimal(str(value.get("nanos") or 0))
    except Exception as exc:  # noqa: BLE001 - Decimal normalizes source values.
        raise ValueError("Invalid money value") from exc
    result = units + nanos / Decimal("1000000000")
    if result <= 0:
        raise ValueError("Money value must be positive")
    return result


def _read_optional_parquet(ref: str) -> list[dict[str, Any]]:
    try:
        if not ref.startswith("s3://") and not Path(ref).exists():
            return []
        return read_parquet_rows(ref)
    except (FileNotFoundError, OSError):
        return []


def repair_observation_history(
    rows: list[dict[str, Any]],
    *,
    key: str,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for raw in rows:
        row = dict(raw)
        grouped.setdefault(str(row[key]), []).append(row)

    repaired: list[dict[str, Any]] = []
    for group in grouped.values():
        ordered = sorted(
            group,
            key=lambda row: (
                str(row["checked_at"]),
                int(row.get("event_order") or 0),
            ),
        )
        first_observed_at = str(ordered[0]["checked_at"])
        for position, row in enumerate(ordered, start=1):
            row["first_observed_at"] = first_observed_at
            row["last_observed_at"] = str(row["checked_at"])
            row["observation_count"] = position
            row["event_order"] = position
            repaired.append(row)
    return sorted(
        repaired,
        key=lambda row: (
            str(row["checked_at"]),
            int(row["series_order"]),
            int(row["event_order"]),
        ),
    )


def latest_observation_rows(
    rows: list[dict[str, Any]],
    *,
    key: str,
) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        item_key = str(row[key])
        previous = latest.get(item_key)
        if previous is None or (
            str(row["checked_at"]),
            int(row["event_order"]),
        ) > (
            str(previous["checked_at"]),
            int(previous["event_order"]),
        ):
            latest[item_key] = dict(row)
    return latest


def _vm_capacity_latest_manifest_ref(output_root: str) -> str:
    return _join(
        output_root,
        "silver/_manifests/vm_capacity/latest.json",
    )


def _coerce_utc(value: datetime | str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        parsed = value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _join(root: str, suffix: str) -> str:
    return "/".join([root.rstrip("/"), suffix.lstrip("/")])
