"""Operator helpers for Curia query catalog inspection and evidence previews."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .gold import read_latest_gold_manifest
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
    manifest = read_latest_gold_manifest(lake_root)
    return {
        "manifest": _operator_manifest_summary(manifest),
        "table_refs": dict(manifest.get("table_refs") or {}),
        "row_counts": dict(manifest.get("row_counts") or {}),
        "provider_scope": list(manifest.get("provider_scope") or []),
        "source_manifest_refs": dict(manifest.get("source_manifest_refs") or {}),
        "source_run_ids": dict(manifest.get("source_run_ids") or {}),
        "source_normalized_refs": dict(manifest.get("source_normalized_refs") or {}),
    }


def run_operator_query(
    *,
    lake_root: str,
    query_id: str,
    version: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    manifest = read_latest_gold_manifest(lake_root)
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
    manifest = read_latest_gold_manifest(lake_root)
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
    manifest = read_latest_gold_manifest(lake_root)
    query = get_catalog_query(query_id, version=version)
    provider_runs = _provider_runs(manifest)
    selected_provider = str(row.get("provider") or row.get("provider_id") or "").strip()
    matching_provider_runs = [
        provider_run
        for provider_run in provider_runs
        if selected_provider and provider_run.get("provider") == selected_provider
    ]
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
    gold_table_refs = {
        table_name: ref
        for table_name, ref in dict(manifest.get("table_refs") or {}).items()
        if table_name in query.tables
    }

    return {
        "query": query.catalog_entry(manifest),
        "row": row,
        "row_refs": {
            "provider": selected_provider or None,
            "listing_id": row.get("listing_id"),
            "benchmark_value_id": row.get("benchmark_value_id"),
            "benchmark_symbol": row.get("benchmark_symbol"),
            "index_symbol": row.get("index_symbol"),
            "source_offer_id": row.get("source_offer_id"),
            "source_run_id": row.get("source_run_id"),
            "raw_ref": row.get("raw_ref"),
            "source_manifest_ref": row.get("source_manifest_ref"),
            "source_normalized_ref": row.get("source_normalized_ref"),
        },
        "trajectory": [
            {
                "layer": "bronze",
                "title": "Raw provider evidence",
                "refs": raw_refs,
                "note": "Provider-shaped payloads retained for audit and replay.",
            },
            {
                "layer": "silver",
                "title": "Normalized provider observations",
                "refs": silver_refs,
                "note": "Common GPU offer schema created from provider evidence.",
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
            "manifest_ref": manifest.get("manifest_ref"),
            "table_refs": gold_table_refs,
            "row_counts": {
                table_name: dict(manifest.get("row_counts") or {}).get(table_name)
                for table_name in query.tables
            },
        },
        "provider_runs": matching_provider_runs or provider_runs,
        "source_manifest_refs": source_manifest_refs,
    }


def preview_operator_ref(
    *,
    lake_root: str,
    ref: str,
    max_bytes: int = MAX_REF_PREVIEW_BYTES,
) -> dict[str, Any]:
    """Preview an allowed ref from the latest operator manifest chain."""
    manifest = read_latest_gold_manifest(lake_root)
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
        except Exception:
            json_value = None
        if json_value is not None:
            payload["json_summary"] = _json_summary(json_value)
            payload["json_preview"] = _compact_json(json_value)
            payload.pop("text", None)
    return payload


def _read_allowed_ref_bytes(ref: str) -> bytes:
    if ref.startswith("s3://") or ref.startswith("/"):
        return read_bytes(ref)
    return _safe_project_ref(ref).read_bytes()


def _read_allowed_ref_json(ref: str) -> Any:
    if ref.startswith("s3://") or ref.startswith("/"):
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
        return read_latest_gold_manifest(lake_root)
    except Exception:
        return None


def _operator_manifest_summary(manifest: dict[str, Any] | None) -> dict[str, Any] | None:
    if manifest is None:
        return None
    return {
        "run_id": manifest.get("run_id"),
        "observed_at": manifest.get("observed_at"),
        "observed_date": manifest.get("observed_date"),
        "provider_scope": manifest.get("provider_scope"),
        "source_run_ids": manifest.get("source_run_ids"),
        "row_counts": manifest.get("row_counts"),
        "methodology_version": manifest.get("methodology_version"),
    }


def _provider_runs(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    provider_scope = list(manifest.get("provider_scope") or [])
    source_manifest_refs = dict(manifest.get("source_manifest_refs") or {})
    source_run_ids = dict(manifest.get("source_run_ids") or {})
    source_normalized_refs = dict(manifest.get("source_normalized_refs") or {})
    runs = []
    for provider in provider_scope:
        manifest_ref = source_manifest_refs.get(provider)
        source_manifest: dict[str, Any] = {}
        if manifest_ref:
            try:
                source_manifest = dict(read_json(str(manifest_ref)))
            except Exception:
                source_manifest = {}
        runs.append(
            {
                "provider": provider,
                "run_id": source_manifest.get("run_id") or source_run_ids.get(provider),
                "observed_at": source_manifest.get("observed_at"),
                "manifest_ref": manifest_ref,
                "raw_ref": source_manifest.get("raw_ref"),
                "normalized_ref": source_manifest.get("normalized_ref") or source_normalized_refs.get(provider),
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
        ]
        if ref
    }
    for provider_run in _provider_runs(manifest):
        for key in ["manifest_ref", "raw_ref", "normalized_ref"]:
            value = provider_run.get(key)
            if value:
                refs.add(str(value))
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
            "keys": sorted(str(key) for key in value.keys())[:25],
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
            return {"_type": "object", "_keys": sorted(str(key) for key in value.keys())[:12]}
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
    return [part.strip() for part in str(value).split(",") if part.strip()]
