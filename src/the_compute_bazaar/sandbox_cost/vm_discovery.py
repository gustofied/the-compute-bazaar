"""Refresh additional VM-capacity and marketplace observations."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Mapping

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
from the_compute_bazaar.sandbox_cost.vm_capacity import (
    latest_observation_rows,
    repair_observation_history,
)


VM_DISCOVERY_UNIVERSE_ID = "public_compute_4unit_8gib_discovery_v1"
VM_DISCOVERY_METHODOLOGY = "classified_vendor_and_marketplace_observations_v1"
VM_DISCOVERY_SOURCE_ORDER = ("aws", "ovhcloud", "oracle_cloud", "akash")
VM_EXPANDED_COHORT_ID = "public_vm_4vcpu_8gib_v2"
VM_EXPANDED_METHODOLOGY = "seven_vendor_exact_shape_hourly_median_iqr_v1"
VM_EXPANDED_PROVIDER_ORDER = (
    "linode",
    "vultr",
    "scaleway",
    "azure",
    "aws",
    "ovhcloud",
    "oracle_cloud",
)
VM_DISCOVERY_TARGET = {
    "processor_quantity": 4,
    "memory_gib": 8,
    "marketplace_storage_gib": 20,
}

AWS_INSTANCE_TYPE = "c7i.xlarge"
AWS_REGION = "eu-west-3"
AWS_LOCATION = "EU (Paris)"
OVH_PLAN_CODE = "d2-8.consumption"
ORACLE_OCPU_SKU = "B93113"
ORACLE_MEMORY_SKU = "B93114"
AKASH_HOURS_PER_MONTH = 730

AWS_SOURCE_URL = (
    "https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/"
    "API_pricing_GetProducts.html"
)
AWS_SPEC_URL = "https://aws.amazon.com/ec2/instance-types/c7i/"
OVH_CATALOG_URL = "https://eu.api.ovh.com/v1/order/catalog/public/cloud"
OVH_SOURCE_URL = (
    "https://eu.api.ovh.com/console-preview/?section=%2Forder&branch=v1"
    "#get-/order/catalog/public/cloud"
)
OVH_SPEC_URL = "https://www.ovhcloud.com/en/public-cloud/prices/"
ORACLE_PRICE_URL = "https://apexapps.oracle.com/pls/apex/cetools/api/v1/products/"
ORACLE_SOURCE_URL = (
    "https://docs.oracle.com/en-us/iaas/Content/Billing/Tasks/"
    "signingup_topic-Estimating_Costs.htm"
)
ORACLE_SPEC_URL = (
    "https://docs.oracle.com/en-us/iaas/Content/Compute/References/computeshapes.htm"
)
AKASH_PRICING_URL = "https://console-api.akash.network/v1/pricing"
AKASH_SOURCE_URL = (
    "https://akash.network/docs/api-documentation/console-api/api-reference/"
)
AKASH_SPEC_URL = "https://akash.network/docs/getting-started/core-concepts/"

SOURCE_LABELS = {
    "aws": "Amazon EC2",
    "ovhcloud": "OVHcloud",
    "oracle_cloud": "Oracle Cloud",
    "akash": "Akash",
}
SOURCE_COLORS = {
    "aws": "#7b6546",
    "ovhcloud": "#466a8a",
    "oracle_cloud": "#8b4c43",
    "akash": "#6e5f86",
}
SOURCE_URLS = {
    "aws": AWS_SOURCE_URL,
    "ovhcloud": OVH_SOURCE_URL,
    "oracle_cloud": ORACLE_SOURCE_URL,
    "akash": AKASH_SOURCE_URL,
}
SPEC_URLS = {
    "aws": AWS_SPEC_URL,
    "ovhcloud": OVH_SPEC_URL,
    "oracle_cloud": ORACLE_SPEC_URL,
    "akash": AKASH_SPEC_URL,
}


@dataclass(frozen=True)
class VmDiscoveryRefresh:
    run_id: str
    checked_at: str
    status: str
    successful_sources: list[str]
    failed_sources: list[str]
    raw_refs: dict[str, list[str]]
    history_ref: str
    current_ref: str
    manifest_ref: str
    history_event_count: int
    current_source_count: int


@dataclass(frozen=True)
class _DiscoveryFetch:
    row: dict[str, Any]
    raw_payloads: list[tuple[str, bytes, str]]


class _DiscoverySourceError(ValueError):
    def __init__(
        self,
        error: Exception,
        raw_payloads: list[tuple[str, bytes, str]],
    ) -> None:
        super().__init__(str(error))
        self.original_error_type = type(error).__name__
        self.raw_payloads = raw_payloads


def refresh_vm_capacity_discovery_sources(
    *,
    output_root: str = "data/sandbox-cost",
    raw_root: str = "data/raw",
    observed_at: datetime | str | None = None,
    session: requests.Session | None = None,
    aws_pricing_client: Any | None = None,
) -> VmDiscoveryRefresh:
    """Retain extra vendor rates and marketplace indications outside cohort v1."""
    lease_ref = _join(output_root, "_locks/vm-discovery-refresh.json")
    with exclusive_lease(lease_ref):
        return _refresh_vm_capacity_discovery_sources_unlocked(
            output_root=output_root,
            raw_root=raw_root,
            observed_at=observed_at,
            session=session,
            aws_pricing_client=aws_pricing_client,
        )


def _refresh_vm_capacity_discovery_sources_unlocked(
    *,
    output_root: str,
    raw_root: str,
    observed_at: datetime | str | None,
    session: requests.Session | None,
    aws_pricing_client: Any | None,
) -> VmDiscoveryRefresh:
    checked = _coerce_utc(observed_at)
    checked_at = checked.isoformat()
    checked_date = checked.date().isoformat()
    run_id = f"vm-discovery-{checked.strftime('%Y%m%dT%H%M%SZ')}"
    client = session or retrying_session()

    state_refs = resolve_vm_discovery_state_refs(output_root)
    state_manifest = read_optional_json(state_refs["manifest_ref"])
    history_ref = state_refs["history_ref"]
    current_ref = state_refs["current_ref"]
    history = _read_optional_parquet(history_ref)
    current_by_source = {
        str(row["source_id"]): dict(row) for row in _read_optional_parquet(current_ref)
    }

    successful: list[str] = []
    failed: list[str] = []
    errors: dict[str, dict[str, str]] = {}
    raw_refs: dict[str, list[str]] = {}
    source_checks: dict[str, dict[str, Any]] = {}
    fetchers: dict[str, Callable[[], _DiscoveryFetch]] = {
        "aws": lambda: _fetch_aws(aws_pricing_client or _default_aws_pricing_client()),
        "ovhcloud": lambda: _fetch_ovhcloud(client),
        "oracle_cloud": lambda: _fetch_oracle_cloud(client),
        "akash": lambda: _fetch_akash(client),
    }

    for source_id in VM_DISCOVERY_SOURCE_ORDER:
        try:
            result = fetchers[source_id]()
            row = {
                **result.row,
                "source_id": source_id,
                "provider_id": source_id,
                "provider_label": SOURCE_LABELS[source_id],
                "series_order": VM_DISCOVERY_SOURCE_ORDER.index(source_id) + 1,
                "universe_id": VM_DISCOVERY_UNIVERSE_ID,
                "methodology_version": VM_DISCOVERY_METHODOLOGY,
                "checked_at": checked_at,
                "source_url": SOURCE_URLS[source_id],
                "spec_url": SPEC_URLS[source_id],
                "color": SOURCE_COLORS[source_id],
            }
            _validate_discovery_row(row)
            row["observation_fingerprint"] = _observation_fingerprint(row)

            previous = current_by_source.get(source_id)
            existing_snapshot = next(
                (
                    item
                    for item in history
                    if item["source_id"] == source_id
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
                        f"Conflicting immutable {source_id} snapshot at {checked_at}"
                    )
                row = dict(existing_snapshot)
                source_raw_refs = json.loads(str(row["raw_refs_json"]))
            else:
                source_raw_refs = _write_raw_payloads(
                    raw_root=raw_root,
                    source_id=source_id,
                    observed_date=checked_date,
                    run_id=run_id,
                    retrieved_at=checked_at,
                    payloads=result.raw_payloads,
                )
                raw_refs[source_id] = source_raw_refs
                row["raw_refs_json"] = json.dumps(
                    source_raw_refs,
                    separators=(",", ":"),
                )
                previous_event_order = max(
                    (
                        int(item["event_order"])
                        for item in history
                        if item["source_id"] == source_id
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
            raw_refs[source_id] = source_raw_refs
            current_by_source[source_id] = row
            successful.append(source_id)
            source_checks[source_id] = {
                "status": "ok",
                "source_class": row["source_class"],
                "observation_kind": row["observation_kind"],
                "plan_id": row["plan_id"],
                "price_usd_per_hour": row["price_usd_per_hour"],
                "raw_refs": source_raw_refs,
                "observation_fingerprint": row["observation_fingerprint"],
            }
        except Exception as exc:  # noqa: BLE001 - isolate each source.
            source_raw_refs: list[str] = []
            raw_capture_error: str | None = None
            if isinstance(exc, _DiscoverySourceError) and exc.raw_payloads:
                try:
                    source_raw_refs = _write_raw_payloads(
                        raw_root=raw_root,
                        source_id=source_id,
                        observed_date=checked_date,
                        run_id=run_id,
                        retrieved_at=checked_at,
                        payloads=exc.raw_payloads,
                    )
                    raw_refs[source_id] = source_raw_refs
                except Exception as capture_exc:  # noqa: BLE001
                    raw_capture_error = str(capture_exc)
            failed.append(source_id)
            errors[source_id] = {
                "error_type": (
                    exc.original_error_type
                    if isinstance(exc, _DiscoverySourceError)
                    else type(exc).__name__
                ),
                "message": str(exc),
            }
            if raw_capture_error:
                errors[source_id]["raw_capture_error"] = raw_capture_error
            source_checks[source_id] = {
                "status": "error",
                **errors[source_id],
                "raw_refs": source_raw_refs,
            }

    if str(state_manifest.get("run_id") or "") == run_id:
        return VmDiscoveryRefresh(
            run_id=run_id,
            checked_at=checked_at,
            status="warning" if failed else str(state_manifest.get("status") or "ok"),
            successful_sources=successful,
            failed_sources=failed,
            raw_refs=raw_refs,
            history_ref=history_ref,
            current_ref=current_ref,
            manifest_ref=state_refs["manifest_ref"],
            history_event_count=len(history),
            current_source_count=len(current_by_source),
        )

    history = repair_observation_history(history, key="source_id")
    current_by_source = latest_observation_rows(history, key="source_id")
    current = sorted(
        current_by_source.values(),
        key=lambda row: int(row["series_order"]),
    )
    _validate_history(history)
    generation_prefix = _join(
        output_root,
        f"silver/vm_discovery/generations/run_id={run_id}",
    )
    history_ref = _join(generation_prefix, "offer_history.parquet")
    current_ref = _join(generation_prefix, "current.parquet")
    manifest_ref = _join(generation_prefix, "manifest.json")
    write_parquet_rows(history_ref, history)
    write_parquet_rows(current_ref, current)

    current_sources = {str(row["source_id"]) for row in current}
    complete = current_sources == set(VM_DISCOVERY_SOURCE_ORDER)
    status = "ok" if not failed and complete else "warning"
    manifest = {
        "manifest_version": "vm_capacity_discovery_manifest_v1",
        "manifest_ref": manifest_ref,
        "run_id": run_id,
        "checked_at": checked_at,
        "status": status,
        "universe_id": VM_DISCOVERY_UNIVERSE_ID,
        "methodology_version": VM_DISCOVERY_METHODOLOGY,
        "target": VM_DISCOVERY_TARGET,
        "source_order": list(VM_DISCOVERY_SOURCE_ORDER),
        "successful_sources": successful,
        "failed_sources": failed,
        "errors": errors,
        "source_checks": source_checks,
        "raw_refs": raw_refs,
        "history_ref": history_ref,
        "current_ref": current_ref,
        "history_event_count": len(history),
        "history_observation_count": len(history),
        "current_source_count": len(current_sources),
        "universe_complete": complete,
        "source_notes": {
            "history": (
                "Every hourly normalized observation is retained, including "
                "unchanged rates. The expanded benchmark begins when all seven "
                "direct vendor inputs are available."
            ),
            "vendor_offers": (
                "AWS, OVHcloud, and Oracle are official vendor prices. Catalog "
                "presence does not prove immediate capacity."
            ),
            "oracle": (
                "Oracle is an exact flexible-shape calculation from two OCPU "
                "and eight memory-GB PAYG meters."
            ),
            "akash": (
                "Akash is a request-specific modeled monthly estimate divided "
                "by 730. It is not a provider bid, lease, or executed price."
            ),
        },
    }
    write_json(manifest_ref, manifest)
    write_json(_vm_discovery_latest_manifest_ref(output_root), manifest)
    return VmDiscoveryRefresh(
        run_id=run_id,
        checked_at=checked_at,
        status=status,
        successful_sources=successful,
        failed_sources=failed,
        raw_refs=raw_refs,
        history_ref=history_ref,
        current_ref=current_ref,
        manifest_ref=manifest_ref,
        history_event_count=len(history),
        current_source_count=len(current_sources),
    )


def resolve_vm_discovery_state_refs(output_root: str) -> dict[str, str]:
    """Resolve the latest immutable discovery generation, with legacy fallback."""
    latest_ref = _vm_discovery_latest_manifest_ref(output_root)
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
            "silver/vm_capacity_discovery_history.parquet",
        ),
        "current_ref": _join(
            output_root,
            "silver/vm_capacity_discovery_current.parquet",
        ),
        "manifest_ref": _join(
            output_root,
            "silver/vm_capacity_discovery_manifest.json",
        ),
    }


def validate_vm_capacity_discovery_history(
    *,
    history_ref: str,
    current_ref: str,
) -> dict[str, Any]:
    history = read_parquet_rows(history_ref)
    current = read_parquet_rows(current_ref)
    _validate_history(history)
    for row in current:
        _validate_discovery_row(row)
    source_ids = {str(row["source_id"]) for row in current}
    unknown = source_ids - set(VM_DISCOVERY_SOURCE_ORDER)
    if unknown:
        raise ValueError(f"Unknown VM discovery sources: {sorted(unknown)}")
    return {
        "history_event_count": len(history),
        "history_observation_count": len(history),
        "current_source_count": len(source_ids),
        "universe_complete": source_ids == set(VM_DISCOVERY_SOURCE_ORDER),
    }


def _default_aws_pricing_client() -> Any:
    try:
        import boto3
    except ImportError as exc:
        raise RuntimeError("AWS Price List discovery requires boto3") from exc
    return boto3.Session(
        profile_name=os.getenv("AWS_PROFILE") or None,
        region_name="us-east-1",
    ).client("pricing", region_name="us-east-1")


def _fetch_aws(client: Any) -> _DiscoveryFetch:
    filters = [
        {"Type": "TERM_MATCH", "Field": "instanceType", "Value": AWS_INSTANCE_TYPE},
        {"Type": "TERM_MATCH", "Field": "location", "Value": AWS_LOCATION},
        {"Type": "TERM_MATCH", "Field": "operatingSystem", "Value": "Linux"},
        {"Type": "TERM_MATCH", "Field": "tenancy", "Value": "Shared"},
        {"Type": "TERM_MATCH", "Field": "preInstalledSw", "Value": "NA"},
        {"Type": "TERM_MATCH", "Field": "capacitystatus", "Value": "Used"},
    ]
    response: Mapping[str, Any] | None = None
    raw_payloads: list[tuple[str, bytes, str]] = []
    try:
        response = client.get_products(
            ServiceCode="AmazonEC2",
            Filters=filters,
            MaxResults=100,
        )
        raw_payload = {
            "mode": "aws_price_list_exact_on_demand_offer",
            "request": {
                "service_code": "AmazonEC2",
                "region": "us-east-1",
                "filters": filters,
            },
            "response": response,
        }
        raw_payloads.append(
            (
                "aws-price-list.json",
                json.dumps(
                    raw_payload,
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                ).encode("utf-8"),
                "application/json",
            )
        )
        price_list = response.get("PriceList")
        if not isinstance(price_list, list) or len(price_list) != 1:
            raise ValueError(f"AWS returned {len(price_list or [])} exact products")
        product = json.loads(str(price_list[0]))
        attributes = _mapping(_mapping(product.get("product")).get("attributes"))
        if (
            attributes.get("instanceType") != AWS_INSTANCE_TYPE
            or attributes.get("regionCode") != AWS_REGION
            or attributes.get("vcpu") != "4"
            or attributes.get("memory") != "8 GiB"
            or attributes.get("operatingSystem") != "Linux"
            or attributes.get("tenancy") != "Shared"
            or attributes.get("marketoption") != "OnDemand"
        ):
            raise ValueError(f"AWS {AWS_INSTANCE_TYPE} product shape drifted")
        on_demand = _mapping(_mapping(product.get("terms")).get("OnDemand"))
        if len(on_demand) != 1:
            raise ValueError("AWS exact product has an ambiguous on-demand term")
        term = _mapping(next(iter(on_demand.values())))
        dimensions = _mapping(term.get("priceDimensions"))
        hourly_dimensions = [
            _mapping(value)
            for value in dimensions.values()
            if _mapping(value).get("unit") == "Hrs"
            and _mapping(value).get("beginRange") == "0"
            and _mapping(value).get("endRange") == "Inf"
        ]
        if len(hourly_dimensions) != 1:
            raise ValueError("AWS exact product has an ambiguous hourly price")
        dimension = hourly_dimensions[0]
        hourly = _positive_number(
            _mapping(dimension.get("pricePerUnit")).get("USD"),
            "AWS on-demand price",
        )
        row = _base_row(
            source_class="direct_vendor_offer",
            observation_kind="published_offer",
            plan_id=AWS_INSTANCE_TYPE,
            plan_label=f"EC2 {AWS_INSTANCE_TYPE}",
            price_usd_per_hour=hourly,
            source_price=hourly,
            source_currency="USD",
            source_price_unit="instance hour",
            normalization_hours=1,
            processor_quantity=4,
            processor_unit="vCPU",
            vcpus=4,
            memory_gib=8,
            storage_gb=None,
            storage_type="EBS",
            storage_included=False,
            storage_scope="EBS storage priced separately",
            region_id=AWS_REGION,
            region_label="Paris",
            cpu_model=str(attributes.get("physicalProcessor") or "not stated"),
            tenancy="shared virtual machine",
            billing_mode="Linux on-demand public offer",
            price_effective_at=str(term.get("effectiveDate") or "") or None,
            availability_status="published_rate",
            executable_offer=True,
            candidate_for_expanded_cohort=True,
            price_formula="one c7i.xlarge instance hour",
        )
        row["source_sku_id"] = str(_mapping(product.get("product")).get("sku") or "")
        row["source_version"] = str(product.get("version") or "")
        row["source_publication_at"] = str(product.get("publicationDate") or "")
        return _DiscoveryFetch(row=row, raw_payloads=raw_payloads)
    except Exception as exc:
        raise _DiscoverySourceError(exc, raw_payloads) from exc


def _fetch_ovhcloud(session: requests.Session) -> _DiscoveryFetch:
    response = session.get(
        OVH_CATALOG_URL,
        params={"ovhSubsidiary": "FR"},
        headers={
            "Accept": "application/json",
            "User-Agent": "the-compute-bazaar/0.1",
        },
        timeout=90,
    )
    raw_payloads = [
        ("ovhcloud-public-catalog.json", response.content, "application/json"),
    ]
    try:
        response.raise_for_status()
        payload = response.json()
        if (
            str(_mapping(payload.get("locale")).get("currencyCode") or "").upper()
            != "EUR"
        ):
            raise ValueError("OVHcloud catalog currency is not EUR")
        matches = [
            item
            for item in _walk_mappings(payload)
            if item.get("planCode") == OVH_PLAN_CODE
        ]
        if len(matches) != 1:
            raise ValueError(
                f"OVHcloud returned {len(matches)} exact {OVH_PLAN_CODE} plans"
            )
        plan = matches[0]
        technical = _mapping(_mapping(plan.get("blobs")).get("technical"))
        cpu = _mapping(technical.get("cpu"))
        memory = _mapping(technical.get("memory"))
        os_data = _mapping(technical.get("os"))
        tags = _mapping(plan.get("blobs")).get("tags")
        if (
            plan.get("product") != "publiccloud-instance"
            or plan.get("pricingType") != "consumption"
            or int(cpu.get("cores") or 0) != 4
            or float(memory.get("size") or 0) != 8
            or str(os_data.get("family") or "").lower() != "linux"
            or not isinstance(tags, list)
            or "active" not in tags
        ):
            raise ValueError(f"OVHcloud {OVH_PLAN_CODE} product shape drifted")
        native_price = _ovh_hourly_price(plan)
        fx = fetch_latest_eur_usd_rate(session)
        raw_payloads.append(
            ("ecb-eur-usd.csv", fx.raw_payload.encode("utf-8"), "text/csv")
        )
        storage = _mapping(technical.get("storage"))
        disks = storage.get("disks")
        first_disk = (
            _mapping(disks[0]) if isinstance(disks, list) and len(disks) == 1 else {}
        )
        storage_gb = _positive_number(
            first_disk.get("capacity"),
            "OVHcloud bundled disk",
        )
        usd_price = native_price * Decimal(str(fx.rate))
        row = _base_row(
            source_class="direct_vendor_offer",
            observation_kind="published_offer",
            plan_id=OVH_PLAN_CODE,
            plan_label=str(plan.get("invoiceName") or "d2-8"),
            price_usd_per_hour=float(usd_price),
            source_price=float(native_price),
            source_currency="EUR",
            source_price_unit="instance hour",
            normalization_hours=1,
            processor_quantity=4,
            processor_unit="vCore",
            vcpus=4,
            memory_gib=8,
            storage_gb=storage_gb,
            storage_type="local NVMe",
            storage_included=True,
            storage_scope="50 GB local NVMe included",
            region_id="fr-catalog",
            region_label="France public catalog; location varies",
            cpu_model=f"{cpu.get('model') or 'vCore'} at {cpu.get('frequency')} GHz",
            tenancy="public cloud instance",
            billing_mode="Linux hourly public offer",
            price_effective_at=None,
            availability_status="active_catalog_rate",
            executable_offer=True,
            candidate_for_expanded_cohort=True,
            price_formula="one d2-8 instance hour",
        )
        row["fx_rate_usd_per_source_currency"] = fx.rate
        row["fx_observed_date"] = fx.observed_date
        return _DiscoveryFetch(row=row, raw_payloads=raw_payloads)
    except Exception as exc:
        raise _DiscoverySourceError(exc, raw_payloads) from exc


def _fetch_oracle_cloud(session: requests.Session) -> _DiscoveryFetch:
    raw_payloads: list[tuple[str, bytes, str]] = []
    try:
        products: dict[str, Mapping[str, Any]] = {}
        last_updated: list[str] = []
        for sku in (ORACLE_OCPU_SKU, ORACLE_MEMORY_SKU):
            response = session.get(
                ORACLE_PRICE_URL,
                params={"partNumber": sku, "currencyCode": "USD"},
                headers={
                    "Accept": "application/json",
                    "User-Agent": "the-compute-bazaar/0.1",
                },
                timeout=60,
            )
            raw_payloads.append(
                (
                    f"oracle-{sku.lower()}.json",
                    response.content,
                    "application/json",
                )
            )
            response.raise_for_status()
            payload = response.json()
            items = payload.get("items") if isinstance(payload, Mapping) else None
            if not isinstance(items, list) or len(items) != 1:
                raise ValueError(f"Oracle returned no exact product for {sku}")
            products[sku] = _mapping(items[0])
            if payload.get("lastUpdated"):
                last_updated.append(str(payload["lastUpdated"]))

        ocpu = products[ORACLE_OCPU_SKU]
        memory = products[ORACLE_MEMORY_SKU]
        if (
            ocpu.get("metricName") != "OCPU Per Hour"
            or memory.get("metricName") != "Gigabyte Per Hour"
            or ocpu.get("serviceCategory") != "Compute - Virtual Machine"
            or memory.get("serviceCategory") != "Compute - Virtual Machine"
        ):
            raise ValueError("Oracle E4 price component semantics drifted")
        ocpu_price = _oracle_payg_usd(ocpu)
        memory_price = _oracle_payg_usd(memory)
        hourly = 2 * ocpu_price + 8 * memory_price
        row = _base_row(
            source_class="direct_vendor_offer",
            observation_kind="composed_published_offer",
            plan_id="VM.Standard.E4.Flex:2ocpu:8gib",
            plan_label="VM.Standard.E4.Flex",
            price_usd_per_hour=hourly,
            source_price=hourly,
            source_currency="USD",
            source_price_unit="composed instance hour",
            normalization_hours=1,
            processor_quantity=4,
            processor_unit="vCPU",
            vcpus=4,
            memory_gib=8,
            storage_gb=None,
            storage_type="block volume",
            storage_included=False,
            storage_scope="boot and block volumes priced separately",
            region_id="global-list",
            region_label="Global public list price",
            cpu_model="AMD EPYC (E4 Flex)",
            tenancy="shared flexible virtual machine",
            billing_mode="PAY_AS_YOU_GO component rates",
            price_effective_at=max(last_updated, default="") or None,
            availability_status="published_rate",
            executable_offer=True,
            candidate_for_expanded_cohort=True,
            price_formula=(f"2 OCPU x ${ocpu_price:.6f} + 8 GB x ${memory_price:.6f}"),
        )
        row["price_components_json"] = json.dumps(
            {
                "ocpu": {
                    "part_number": ORACLE_OCPU_SKU,
                    "quantity": 2,
                    "unit_price_usd": ocpu_price,
                },
                "memory": {
                    "part_number": ORACLE_MEMORY_SKU,
                    "quantity_gb": 8,
                    "unit_price_usd": memory_price,
                },
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return _DiscoveryFetch(row=row, raw_payloads=raw_payloads)
    except Exception as exc:
        raise _DiscoverySourceError(exc, raw_payloads) from exc


def _fetch_akash(session: requests.Session) -> _DiscoveryFetch:
    request_payload = {
        "cpu": VM_DISCOVERY_TARGET["processor_quantity"] * 1000,
        "memory": VM_DISCOVERY_TARGET["memory_gib"] * 1024**3,
        "storage": VM_DISCOVERY_TARGET["marketplace_storage_gib"] * 1024**3,
    }
    response = session.post(
        AKASH_PRICING_URL,
        json=request_payload,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "the-compute-bazaar/0.1",
        },
        timeout=60,
    )
    raw_payloads = [
        ("akash-pricing.json", response.content, "application/json"),
        (
            "request.json",
            json.dumps(
                request_payload,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8"),
            "application/json",
        ),
    ]
    try:
        response.raise_for_status()
        payload = response.json()
        if _mapping(payload.get("spec")) != request_payload:
            raise ValueError("Akash pricing response does not echo the request")
        monthly = _positive_number(payload.get("akash"), "Akash monthly estimate")
        hourly = monthly / AKASH_HOURS_PER_MONTH
        row = _base_row(
            source_class="marketplace_indication",
            observation_kind="request_estimate",
            plan_id="cpu-4000-memory-8gib-storage-20gib",
            plan_label="4 CPU units, 8 GiB, 20 GiB request",
            price_usd_per_hour=hourly,
            source_price=monthly,
            source_currency="USD",
            source_price_unit="modeled month",
            normalization_hours=AKASH_HOURS_PER_MONTH,
            processor_quantity=4,
            processor_unit="Akash CPU unit",
            vcpus=None,
            memory_gib=8,
            storage_gb=20,
            storage_type="request storage",
            storage_included=True,
            storage_scope="20 GiB included in the modeled request",
            region_id="akash-network",
            region_label="Akash provider network",
            cpu_model="provider-specific",
            tenancy="marketplace provider-specific",
            billing_mode="public monthly estimate normalized over 730 hours",
            price_effective_at=None,
            availability_status="modeled_estimate",
            executable_offer=False,
            candidate_for_expanded_cohort=False,
            price_formula=f"${monthly:.6f} modeled month / 730 hours",
        )
        row["comparison_estimates_json"] = json.dumps(
            {
                key: payload.get(key)
                for key in ("aws", "gcp", "azure")
                if payload.get(key) is not None
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return _DiscoveryFetch(row=row, raw_payloads=raw_payloads)
    except Exception as exc:
        raise _DiscoverySourceError(exc, raw_payloads) from exc


def _base_row(
    *,
    source_class: str,
    observation_kind: str,
    plan_id: str,
    plan_label: str,
    price_usd_per_hour: float,
    source_price: float,
    source_currency: str,
    source_price_unit: str,
    normalization_hours: int,
    processor_quantity: int,
    processor_unit: str,
    vcpus: int | None,
    memory_gib: float,
    storage_gb: float | None,
    storage_type: str,
    storage_included: bool,
    storage_scope: str,
    region_id: str,
    region_label: str,
    cpu_model: str,
    tenancy: str,
    billing_mode: str,
    price_effective_at: str | None,
    availability_status: str,
    executable_offer: bool,
    candidate_for_expanded_cohort: bool,
    price_formula: str,
) -> dict[str, Any]:
    return {
        "source_class": source_class,
        "observation_kind": observation_kind,
        "plan_id": plan_id,
        "plan_label": plan_label,
        "price_usd_per_hour": float(price_usd_per_hour),
        "source_price": float(source_price),
        "source_currency": source_currency,
        "source_price_unit": source_price_unit,
        "normalization_hours": normalization_hours,
        "processor_quantity": processor_quantity,
        "processor_unit": processor_unit,
        "vcpus": vcpus,
        "memory_gib": float(memory_gib),
        "storage_gb": float(storage_gb) if storage_gb is not None else None,
        "storage_type": storage_type,
        "storage_included": storage_included,
        "storage_scope": storage_scope,
        "region_id": region_id,
        "region_label": region_label,
        "cpu_model": cpu_model,
        "tenancy": tenancy,
        "billing_mode": billing_mode,
        "price_effective_at": price_effective_at,
        "availability_status": availability_status,
        "capacity_confirmed": False,
        "executable_offer": executable_offer,
        "benchmark_eligible": False,
        "candidate_for_expanded_cohort": candidate_for_expanded_cohort,
        "price_formula": price_formula,
    }


def _validate_discovery_row(row: Mapping[str, Any]) -> None:
    required = (
        "source_id",
        "source_class",
        "observation_kind",
        "plan_id",
        "price_usd_per_hour",
        "source_price",
        "source_currency",
        "source_price_unit",
        "processor_quantity",
        "processor_unit",
        "memory_gib",
        "storage_included",
        "storage_scope",
        "region_id",
        "universe_id",
    )
    missing = [key for key in required if row.get(key) is None]
    if missing:
        raise ValueError(f"VM discovery row is missing fields: {missing}")
    source_id = str(row["source_id"])
    if source_id not in VM_DISCOVERY_SOURCE_ORDER:
        raise ValueError(f"Unexpected VM discovery source {source_id}")
    if str(row["universe_id"]) != VM_DISCOVERY_UNIVERSE_ID:
        raise ValueError(f"Unexpected VM discovery universe {row['universe_id']}")
    if int(row["processor_quantity"]) != 4 or float(row["memory_gib"]) != 8:
        raise ValueError(f"Incompatible discovery request shape for {source_id}")
    if source_id == "akash":
        if (
            row["source_class"] != "marketplace_indication"
            or row.get("vcpus") is not None
            or row.get("executable_offer") is not False
        ):
            raise ValueError("Akash discovery row must remain a non-bid indication")
    elif (
        row["source_class"] != "direct_vendor_offer"
        or int(row.get("vcpus") or 0) != 4
        or row.get("executable_offer") is not True
    ):
        raise ValueError(f"Direct discovery source {source_id} lost exact shape")
    if row.get("benchmark_eligible") is not False:
        raise ValueError("Discovery rows cannot enter benchmark v1")
    _positive_number(row["price_usd_per_hour"], "discovery hourly price")


def _validate_history(rows: list[dict[str, Any]]) -> None:
    seen: set[tuple[str, int]] = set()
    snapshots: set[tuple[str, str]] = set()
    for row in rows:
        _validate_discovery_row(row)
        key = (str(row["source_id"]), int(row["event_order"]))
        if key in seen:
            raise ValueError(f"Duplicate VM discovery event {key}")
        seen.add(key)
        snapshot_key = (
            str(row["source_id"]),
            str(row["checked_at"]),
        )
        if snapshot_key in snapshots:
            raise ValueError(
                f"VM discovery history repeats {row['source_id']} at "
                f"{row['checked_at']}"
            )
        snapshots.add(snapshot_key)


def _observation_fingerprint(row: Mapping[str, Any]) -> str:
    excluded = {
        "checked_at",
        "first_observed_at",
        "last_observed_at",
        "observation_count",
        "event_order",
        "raw_refs_json",
        "observation_fingerprint",
    }
    payload = json.dumps(
        {key: value for key, value in row.items() if key not in excluded},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _write_raw_payloads(
    *,
    raw_root: str,
    source_id: str,
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
            "sandbox-cost/vm-capacity-discovery/"
            f"source={source_id}/date={observed_date}/run_id={run_id}"
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
            "manifest_version": "vm_capacity_discovery_raw_capture_v1",
            "source_id": source_id,
            "run_id": run_id,
            "retrieved_at": retrieved_at,
            "files": files,
        },
    )
    refs.append(manifest_ref)
    return refs


def _ovh_hourly_price(plan: Mapping[str, Any]) -> Decimal:
    pricings = plan.get("pricings")
    if not isinstance(pricings, list):
        raise ValueError("OVHcloud plan has no pricings")
    matches = [
        _mapping(pricing)
        for pricing in pricings
        if _mapping(pricing).get("intervalUnit") == "hour"
        and _mapping(pricing).get("interval") == 1
        and _mapping(pricing).get("type") == "consumption"
    ]
    if len(matches) != 1:
        raise ValueError("OVHcloud plan has an ambiguous hourly price")
    raw = _positive_number(matches[0].get("price"), "OVHcloud hourly price")
    return Decimal(str(raw)) / Decimal("100000000")


def _oracle_payg_usd(product: Mapping[str, Any]) -> float:
    localizations = product.get("currencyCodeLocalizations")
    if not isinstance(localizations, list):
        raise ValueError("Oracle price product has no currency localizations")
    for localization in localizations:
        row = _mapping(localization)
        if row.get("currencyCode") != "USD":
            continue
        prices = row.get("prices")
        if not isinstance(prices, list):
            continue
        matches = [
            _mapping(price)
            for price in prices
            if _mapping(price).get("model") == "PAY_AS_YOU_GO"
        ]
        if len(matches) == 1:
            return _positive_number(
                matches[0].get("value"),
                "Oracle PAYG price",
            )
    raise ValueError("Oracle price product has no exact USD PAYG value")


def _walk_mappings(value: Any) -> list[Mapping[str, Any]]:
    rows: list[Mapping[str, Any]] = []
    if isinstance(value, Mapping):
        rows.append(value)
        for nested in value.values():
            rows.extend(_walk_mappings(nested))
    elif isinstance(value, list):
        for nested in value:
            rows.extend(_walk_mappings(nested))
    return rows


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _positive_number(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} is not numeric") from exc
    if not number > 0:
        raise ValueError(f"{label} must be positive")
    return number


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


def _read_optional_parquet(ref: str) -> list[dict[str, Any]]:
    try:
        return read_parquet_rows(ref)
    except (FileNotFoundError, OSError):
        return []


def _vm_discovery_latest_manifest_ref(output_root: str) -> str:
    return _join(
        output_root,
        "silver/_manifests/vm_discovery/latest.json",
    )


def _join(root: str, suffix: str) -> str:
    return f"{root.rstrip('/')}/{suffix.lstrip('/')}"
