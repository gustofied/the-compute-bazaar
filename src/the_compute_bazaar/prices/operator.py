"""Operator helpers for Curia query catalog inspection and evidence previews."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from the_compute_bazaar.sandbox_cost.pipeline import read_latest_sandbox_manifest

from .gold import read_latest_gold_manifest
from .market_run import read_latest_market_run
from .query_catalog import (
    DEFAULT_QUERY_CATALOG_PATH,
    PROJECT_ROOT,
    get_catalog_query,
    list_catalog_queries,
    load_query_catalog,
    run_catalog_query,
    run_scratch_query,
    scratch_query_entry,
)
from .storage import read_bytes, read_json

MAX_REF_PREVIEW_BYTES = 128 * 1024


def list_operator_queries(*, lake_root: str | None = None) -> dict[str, Any]:
    manifest = _optional_latest_manifest(lake_root)
    return {
        "manifest": _operator_manifest_summary(manifest),
        "queries": list_catalog_queries(manifest=manifest),
        "scratch": scratch_query_entry(manifest) if manifest is not None else None,
    }


def read_operator_manifest(*, lake_root: str) -> dict[str, Any]:
    manifest = _read_operator_manifest(lake_root)
    return {
        "manifest": _operator_manifest_summary(manifest),
        "table_refs": dict(manifest.get("table_refs") or {}),
        "row_counts": dict(manifest.get("row_counts") or {}),
        "provider_scope": list(manifest.get("provider_scope") or []),
        "source_manifest_refs": dict(manifest.get("source_manifest_refs") or {}),
        "source_run_ids": dict(manifest.get("source_run_ids") or {}),
        "source_normalized_refs": dict(manifest.get("source_normalized_refs") or {}),
        "source_market_state_refs": dict(
            manifest.get("source_market_state_refs") or {}
        ),
        "component_manifests": _component_manifest_summaries(manifest),
    }


def run_operator_query(
    *,
    lake_root: str,
    query_id: str,
    version: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    manifest = _read_operator_manifest(lake_root)
    result = run_catalog_query(
        manifest=manifest,
        query_id=query_id,
        version=version,
        limit=limit,
    )
    return {
        "manifest": _operator_manifest_summary(manifest),
        **result,
    }


def run_operator_sql(
    *,
    lake_root: str,
    sql: str,
    limit: int | None = None,
) -> dict[str, Any]:
    manifest = _read_operator_manifest(lake_root)
    result = run_scratch_query(
        manifest=manifest,
        sql=sql,
        limit=limit,
    )
    return {
        "manifest": _operator_manifest_summary(manifest),
        **result,
    }


def trace_operator_row(
    *,
    lake_root: str,
    query_id: str,
    row: dict[str, Any],
    version: str | None = None,
) -> dict[str, Any]:
    manifest = _read_operator_manifest(lake_root)
    query = get_catalog_query(query_id, version=version)
    component_name, component_manifest = _query_component(manifest, query.tables)
    provider_runs = _provider_runs(manifest)
    selected_provider = str(row.get("provider") or row.get("provider_id") or "").strip()
    matching_provider_runs = [
        provider_run
        for provider_run in provider_runs
        if selected_provider and provider_run.get("provider") == selected_provider
    ]
    if component_name in {"sandbox", "combined"}:
        combined_provider_runs = (
            matching_provider_runs or provider_runs
            if component_name == "combined"
            else []
        )
        raw_refs = _dedupe(
            [
                *_ref_values(component_manifest.get("bronze_refs")),
                *_split_refs(row.get("raw_ref")),
                *_split_refs(row.get("raw_refs_json")),
                *[
                    str(provider_run.get("raw_ref"))
                    for provider_run in combined_provider_runs
                    if provider_run.get("raw_ref")
                ],
            ]
        )
        silver_refs = _dedupe(
            [
                *_ref_values(component_manifest.get("silver_refs")),
                *_split_refs(row.get("source_normalized_ref")),
                *[
                    str(provider_run.get("normalized_ref"))
                    for provider_run in combined_provider_runs
                    if provider_run.get("normalized_ref")
                ],
            ]
        )
        source_manifest_refs = _dedupe(
            [
                str(component_manifest.get("manifest_ref") or ""),
                *_source_manifest_refs(component_manifest),
            ]
        )
        lineage_provider_runs = combined_provider_runs
        if component_name == "combined":
            bronze_note = (
                "GPU provider payloads plus reviewed VM, sandbox, and benchmark "
                "evidence retained for audit and replay."
            )
            silver_note = (
                "Comparable GPU offers and explicitly shaped CPU/sandbox "
                "observations, with their unlike units kept separate."
            )
        else:
            bronze_note = (
                "Reviewed rate cards, exact-shape VM captures, and public benchmark "
                "evidence retained for audit and replay."
            )
            silver_note = (
                "Normalized rates, machine shapes, workload runs, and source timing "
                "with incompatible observations kept separate."
            )
    else:
        raw_refs = _dedupe(
            [
                str(row.get("raw_ref")) if row.get("raw_ref") else "",
                *[
                    str(provider_run.get("raw_ref"))
                    for provider_run in (matching_provider_runs or provider_runs)
                    if provider_run.get("raw_ref")
                ],
            ]
        )
        silver_refs = _dedupe(
            [
                *_split_refs(row.get("source_normalized_ref")),
                *_split_refs(row.get("source_market_state_ref")),
                *[
                    str(provider_run.get("normalized_ref"))
                    for provider_run in (matching_provider_runs or provider_runs)
                    if provider_run.get("normalized_ref")
                ],
            ]
        )
        source_manifest_refs = _dedupe(
            [
                *_split_refs(row.get("source_manifest_ref")),
                *[
                    str(provider_run.get("manifest_ref"))
                    for provider_run in (matching_provider_runs or provider_runs)
                    if provider_run.get("manifest_ref")
                ],
            ]
        )
        lineage_provider_runs = matching_provider_runs or provider_runs
        bronze_note = "Provider-shaped payloads retained for audit and replay."
        silver_note = "Common GPU offer schema created from provider evidence."
    gold_table_refs = {
        table_name: ref
        for table_name, ref in dict(manifest.get("table_refs") or {}).items()
        if table_name in query.tables
    }
    component_manifest_refs = _query_component_manifest_refs(
        manifest,
        component_name=component_name,
    )
    component_runs = _query_component_runs(
        manifest,
        component_name=component_name,
    )

    return {
        "query": query.catalog_entry(manifest),
        "row": row,
        "row_refs": {
            "provider": selected_provider or None,
            "listing_id": row.get("listing_id"),
            "benchmark_value_id": row.get("benchmark_value_id"),
            "benchmark_symbol": row.get("benchmark_symbol"),
            "index_symbol": row.get("index_symbol"),
            "series_id": row.get("series_id"),
            "series_label": row.get("series_label"),
            "benchmark_run_id": row.get("benchmark_run_id"),
            "source_offer_id": row.get("source_offer_id"),
            "source_run_id": row.get("source_run_id"),
            "source_url": row.get("source_url"),
            "raw_ref": row.get("raw_ref"),
            "source_manifest_ref": row.get("source_manifest_ref"),
            "source_normalized_ref": row.get("source_normalized_ref"),
            "source_market_state_ref": row.get("source_market_state_ref"),
        },
        "trajectory": [
            {
                "layer": "bronze",
                "title": "Raw provider evidence",
                "refs": raw_refs,
                "note": bronze_note,
            },
            {
                "layer": "silver",
                "title": "Normalized provider observations",
                "refs": silver_refs,
                "note": silver_note,
            },
            {
                "layer": "curia",
                "title": "Curia / DataFusion query",
                "refs": [query.catalog_entry(manifest)["sql_path"], *list(gold_table_refs.values())],
                "note": f"Query `{query.query_id}` {query.version} over {', '.join(query.tables)}.",
            },
            {
                "layer": "gold",
                "title": "Gold market object",
                "refs": list(gold_table_refs.values()),
                "note": "Curia-authored product truth read by dashboards, CLI, and future agents.",
            },
        ],
        "gold": {
            "manifest": _operator_manifest_summary(manifest),
            "component": component_name,
            "component_runs": {
                name: details["run_id"] for name, details in component_runs.items()
            },
            "component_observed_at": {
                name: details["observed_at"]
                for name, details in component_runs.items()
            },
            "manifest_ref": (
                component_manifest_refs[0]
                if len(component_manifest_refs) == 1
                else None
            ),
            "manifest_refs": component_manifest_refs,
            "table_refs": gold_table_refs,
            "row_counts": {
                table_name: dict(manifest.get("row_counts") or {}).get(table_name)
                for table_name in query.tables
            },
        },
        "provider_runs": lineage_provider_runs,
        "source_manifest_refs": source_manifest_refs,
    }


def preview_operator_ref(
    *,
    lake_root: str,
    ref: str,
    max_bytes: int = MAX_REF_PREVIEW_BYTES,
) -> dict[str, Any]:
    """Preview an allowed ref from the latest operator manifest chain."""
    manifest = _read_operator_manifest(lake_root)
    allowed_refs = _allowed_refs(manifest)
    normalized_ref = str(ref or "").strip()
    if not normalized_ref:
        raise ValueError("Missing ref")
    if normalized_ref not in allowed_refs:
        raise PermissionError("Ref is not part of the latest operator manifest chain")

    if normalized_ref.endswith(".parquet"):
        return {
            "ref": normalized_ref,
            "kind": "parquet",
            "previewable": False,
            "message": "Parquet refs are queryable through cataloged DataFusion SQL; raw preview is disabled.",
        }

    bounded_bytes = max(1, min(MAX_REF_PREVIEW_BYTES, int(max_bytes)))
    data = _read_allowed_ref_bytes(normalized_ref)
    preview_bytes = data[:bounded_bytes]
    text = preview_bytes.decode("utf-8", errors="replace")
    payload: dict[str, Any] = {
        "ref": normalized_ref,
        "kind": _guess_ref_kind(normalized_ref),
        "previewable": True,
        "byte_count": len(data),
        "preview_byte_count": len(preview_bytes),
        "truncated": len(data) > bounded_bytes,
        "text": text,
    }
    if normalized_ref.endswith(".json"):
        try:
            json_value = _read_allowed_ref_json(normalized_ref)
        except Exception:  # noqa: BLE001 - an unreadable JSON preview should fall back to text.
            json_value = None
        if json_value is not None:
            payload["json_summary"] = _json_summary(json_value)
            payload["json_preview"] = _compact_json(json_value)
            payload.pop("text", None)
    return payload


def _read_allowed_ref_bytes(ref: str) -> bytes:
    if ref.startswith(("s3://", "/")):
        return read_bytes(ref)
    return _safe_project_ref(ref).read_bytes()


def _read_allowed_ref_json(ref: str) -> Any:
    if ref.startswith(("s3://", "/")):
        return read_json(ref)
    return read_json(str(_safe_project_ref(ref)))


def _safe_project_ref(ref: str) -> Path:
    path = (PROJECT_ROOT / ref).resolve()
    if PROJECT_ROOT.resolve() != path and PROJECT_ROOT.resolve() not in path.parents:
        raise PermissionError("Ref escapes the project root")
    return path


def _optional_latest_manifest(lake_root: str | None) -> dict[str, Any] | None:
    if not lake_root:
        return None
    try:
        return _read_operator_manifest(lake_root)
    except Exception:  # noqa: BLE001 - catalog discovery remains usable before gold exists.
        return None


def _operator_manifest_summary(manifest: dict[str, Any] | None) -> dict[str, Any] | None:
    if manifest is None:
        return None
    market_run = dict(manifest.get("market_run") or {})
    successful_providers = list(market_run.get("successful_providers") or [])
    failed_providers = list(market_run.get("failed_providers") or [])
    provider_scope = list(
        market_run.get("providers") or manifest.get("provider_scope") or []
    )
    component_manifests = dict(manifest.get("component_manifests") or {})
    return {
        "run_id": manifest.get("run_id"),
        "observed_at": manifest.get("observed_at"),
        "observed_date": manifest.get("observed_date"),
        "provider_scope": provider_scope,
        "source_run_ids": manifest.get("source_run_ids"),
        "row_counts": manifest.get("row_counts"),
        "methodology_version": manifest.get("methodology_version"),
        "market_run_id": market_run.get("market_run_id"),
        "status": market_run.get("status") or "gold_ready",
        "data_quality_status": market_run.get("data_quality_status"),
        "successful_provider_count": len(successful_providers),
        "failed_providers": failed_providers,
        "provider_count": len(provider_scope),
        "table_count": len(dict(manifest.get("table_refs") or {})),
        "gpu_table_count": len(
            dict(dict(component_manifests.get("gpu") or {}).get("table_refs") or {})
        ),
        "sandbox_table_count": len(
            dict(
                dict(component_manifests.get("sandbox") or {}).get("table_refs")
                or {}
            )
        ),
        "sandbox_build_id": dict(component_manifests.get("sandbox") or {}).get(
            "build_id"
        ),
    }


def _read_operator_manifest(lake_root: str) -> dict[str, Any]:
    gpu_manifest = dict(read_latest_gold_manifest(lake_root))
    sandbox_manifest = _optional_sandbox_manifest(lake_root)
    market_run = _optional_market_run(lake_root)
    table_refs = dict(gpu_manifest.get("table_refs") or {})
    row_counts = dict(gpu_manifest.get("row_counts") or {})
    if sandbox_manifest:
        table_refs.update(dict(sandbox_manifest.get("table_refs") or {}))
        row_counts.update(dict(sandbox_manifest.get("row_counts") or {}))

    return {
        **gpu_manifest,
        "table_refs": table_refs,
        "row_counts": row_counts,
        "market_run": market_run,
        "component_manifests": {
            "gpu": gpu_manifest,
            **({"sandbox": sandbox_manifest} if sandbox_manifest else {}),
        },
    }


def _optional_sandbox_manifest(lake_root: str) -> dict[str, Any]:
    output_root = "/".join([lake_root.rstrip("/"), "sandbox_cost"])
    try:
        return dict(read_latest_sandbox_manifest(output_root))
    except Exception:  # noqa: BLE001 - sandbox gold is an optional operator component.
        return {}


def _optional_market_run(lake_root: str) -> dict[str, Any]:
    try:
        return dict(read_latest_market_run(lake_root))
    except Exception:  # noqa: BLE001 - older local gold builds have no market-run manifest.
        return {}


def _component_manifest_summaries(manifest: dict[str, Any]) -> dict[str, Any]:
    summaries: dict[str, Any] = {}
    for name, component in dict(manifest.get("component_manifests") or {}).items():
        component_manifest = dict(component or {})
        summaries[name] = {
            "run_id": component_manifest.get("run_id")
            or component_manifest.get("build_id"),
            "manifest_version": component_manifest.get("manifest_version"),
            "manifest_ref": component_manifest.get("manifest_ref"),
            "observed_at": component_manifest.get("observed_at")
            or component_manifest.get("built_at"),
            "table_count": len(dict(component_manifest.get("table_refs") or {})),
            "row_counts": dict(component_manifest.get("row_counts") or {}),
        }
    return summaries


def _query_component(
    manifest: dict[str, Any],
    query_tables: tuple[str, ...],
) -> tuple[str, dict[str, Any]]:
    components = dict(manifest.get("component_manifests") or {})
    sandbox = dict(components.get("sandbox") or {})
    sandbox_tables = set(dict(sandbox.get("table_refs") or {}))
    if query_tables and set(query_tables).issubset(sandbox_tables):
        return "sandbox", sandbox
    if set(query_tables) & sandbox_tables:
        return "combined", sandbox
    return "gpu", dict(components.get("gpu") or manifest)


def _query_component_manifest_refs(
    manifest: dict[str, Any],
    *,
    component_name: str,
) -> list[str]:
    return _dedupe(
        [
            str(details["manifest_ref"] or "")
            for details in _query_component_runs(
                manifest,
                component_name=component_name,
            ).values()
        ]
    )


def _query_component_runs(
    manifest: dict[str, Any],
    *,
    component_name: str,
) -> dict[str, dict[str, Any]]:
    components = dict(manifest.get("component_manifests") or {})
    names = ["gpu", "sandbox"] if component_name == "combined" else [component_name]
    result: dict[str, dict[str, Any]] = {}
    for name in names:
        component = dict(components.get(name) or {})
        if not component:
            continue
        result[name] = {
            "run_id": component.get("run_id") or component.get("build_id"),
            "observed_at": component.get("observed_at") or component.get("built_at"),
            "manifest_ref": component.get("manifest_ref"),
        }
    return result


def _provider_runs(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    provider_scope = list(manifest.get("provider_scope") or [])
    source_manifest_refs = dict(manifest.get("source_manifest_refs") or {})
    source_run_ids = dict(manifest.get("source_run_ids") or {})
    source_normalized_refs = dict(manifest.get("source_normalized_refs") or {})
    source_market_state_refs = dict(manifest.get("source_market_state_refs") or {})
    runs = []
    for provider in provider_scope:
        manifest_ref = source_manifest_refs.get(provider)
        source_manifest: dict[str, Any] = {}
        if manifest_ref:
            try:
                source_manifest = dict(read_json(str(manifest_ref)))
            except Exception:  # noqa: BLE001 - one unreadable source must not hide other runs.
                source_manifest = {}
        runs.append(
            {
                "provider": provider,
                "run_id": source_manifest.get("run_id") or source_run_ids.get(provider),
                "observed_at": source_manifest.get("observed_at"),
                "manifest_ref": manifest_ref,
                "raw_ref": source_manifest.get("raw_ref"),
                "normalized_ref": source_manifest.get("normalized_ref") or source_normalized_refs.get(provider),
                "market_state_ref": source_manifest.get("market_state_ref")
                or source_market_state_refs.get(provider),
                "market_state_observation_count": source_manifest.get(
                    "market_state_observation_count"
                ),
                "raw_offer_count": source_manifest.get("raw_offer_count"),
                "normalized_offer_count": source_manifest.get("normalized_offer_count"),
                "published_events": source_manifest.get("published_events"),
                "unknown_gpu_names": source_manifest.get("unknown_gpu_names"),
            }
        )
    return runs


def _allowed_refs(manifest: dict[str, Any]) -> set[str]:
    refs = {
        str(ref)
        for ref in [
            manifest.get("manifest_ref"),
            *dict(manifest.get("table_refs") or {}).values(),
            *dict(manifest.get("source_manifest_refs") or {}).values(),
            *dict(manifest.get("source_normalized_refs") or {}).values(),
            *dict(manifest.get("source_market_state_refs") or {}).values(),
        ]
        if ref
    }
    for provider_run in _provider_runs(manifest):
        for key in ["manifest_ref", "raw_ref", "normalized_ref", "market_state_ref"]:
            value = provider_run.get(key)
            if value:
                refs.add(str(value))
    for component in dict(manifest.get("component_manifests") or {}).values():
        component_manifest = dict(component or {})
        refs.update(_ref_values(component_manifest.get("manifest_ref")))
        refs.update(_ref_values(component_manifest.get("bronze_refs")))
        refs.update(_ref_values(component_manifest.get("silver_refs")))
        refs.update(_ref_values(component_manifest.get("table_refs")))
        refs.update(_source_manifest_refs(component_manifest))
    refs.add(str(DEFAULT_QUERY_CATALOG_PATH.relative_to(PROJECT_ROOT)))
    for query in load_query_catalog():
        refs.add(str(query.sql_path.relative_to(PROJECT_ROOT)))
    return refs


def _guess_ref_kind(ref: str) -> str:
    if ref.endswith(".json"):
        return "json"
    if ref.endswith(".jsonl"):
        return "jsonl"
    if ref.endswith(".parquet"):
        return "parquet"
    if ref.endswith(".sql"):
        return "sql"
    return "text"


def _json_summary(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        summary: dict[str, Any] = {
            "type": "object",
            "keys": sorted(str(key) for key in value)[:25],
        }
        for key in ["offers", "executors", "data", "pages"]:
            child = value.get(key)
            if isinstance(child, list):
                summary[f"{key}_count"] = len(child)
        return summary
    if isinstance(value, list):
        return {"type": "array", "item_count": len(value)}
    return {"type": type(value).__name__}


def _compact_json(value: Any, *, depth: int = 0) -> Any:
    if depth >= 3:
        if isinstance(value, dict):
            return {"_type": "object", "_keys": sorted(str(key) for key in value)[:12]}
        if isinstance(value, list):
            return {"_type": "array", "_count": len(value)}
        return value
    if isinstance(value, dict):
        return {
            str(key): _compact_json(child, depth=depth + 1)
            for key, child in list(value.items())[:20]
        }
    if isinstance(value, list):
        return [_compact_json(child, depth=depth + 1) for child in value[:5]]
    return value


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _split_refs(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except (TypeError, ValueError):
            parsed = None
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    return [part.strip() for part in text.split(",") if part.strip()]


def _ref_values(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, dict):
        refs: list[str] = []
        for child in value.values():
            refs.extend(_ref_values(child))
        return refs
    if isinstance(value, (list, tuple, set)):
        refs = []
        for child in value:
            refs.extend(_ref_values(child))
        return refs
    text = str(value).strip()
    return [text] if text else []


def _source_manifest_refs(manifest: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for key, value in manifest.items():
        if key.endswith("manifest_ref") and value:
            refs.extend(_ref_values(value))
        elif key.endswith("source_manifest") and isinstance(value, dict):
            refs.extend(_ref_values(value.get("manifest_ref")))
    return _dedupe(refs)
