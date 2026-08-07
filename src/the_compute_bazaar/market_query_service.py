"""Shared read-only query service over the latest market run."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from copy import deepcopy
from threading import RLock
from typing import Any

from .prices.gold_manifest import read_latest_gold_manifest
from .prices.gold_queries import (
    query_gold_gpu_availability,
    query_gold_gpu_price_index,
    query_gold_gpu_price_index_history,
    query_gold_listings,
    query_gold_prime_frontier_offer_market,
    query_gold_provider_comparison,
)
from .prices.query_catalog import (
    bounded_query_limit,
    list_catalog_queries,
    run_catalog_query,
    run_scratch_query,
)


DEFAULT_CACHE_SIZE = 64
PRIVATE_FIELD_NAMES = {
    "bronze_refs",
    "manifest_ref",
    "raw_ref",
    "silver_refs",
    "source_manifest_ref",
    "source_normalized_ref",
    "table_refs",
}
PUBLIC_MANIFEST_FIELDS = (
    "contract",
    "methodology",
    "run_id",
    "observed_at",
    "observed_date",
    "provider_scope",
    "row_counts",
    "source_run_ids",
)


class MarketQueryService:
    """Run bounded DataFusion queries against one market run at a time."""

    def __init__(self, *, lake_root: str, cache_size: int = DEFAULT_CACHE_SIZE) -> None:
        self.lake_root = lake_root.rstrip("/")
        self.cache_size = max(1, int(cache_size))
        self._cache: OrderedDict[tuple[Any, ...], Any] = OrderedDict()
        self._cache_lock = RLock()

    def manifest(self) -> dict[str, Any]:
        manifest = self._latest_manifest()
        payload = {
            field: deepcopy(manifest.get(field))
            for field in PUBLIC_MANIFEST_FIELDS
            if field in manifest
        }
        payload["tables"] = sorted(
            name for name, ref in dict(manifest.get("table_refs") or {}).items() if ref
        )
        return payload

    def catalog(self) -> dict[str, Any]:
        manifest = self._latest_manifest()
        run = _public_manifest(manifest)
        run["tables"] = sorted(
            name for name, ref in dict(manifest.get("table_refs") or {}).items() if ref
        )
        return {
            "run": run,
            "queries": list_catalog_queries(manifest=manifest),
        }

    def saved_query(
        self,
        *,
        query_id: str,
        limit: int | None = None,
    ) -> dict[str, Any]:
        manifest = self._latest_manifest()
        selected_limit = bounded_query_limit(limit or 100)
        return self._cached(
            manifest,
            ("saved_query", query_id, selected_limit),
            lambda: _with_public_run(
                _sanitize_public_value(
                    run_catalog_query(
                        manifest=manifest,
                        query_id=query_id,
                        limit=selected_limit,
                    )
                ),
                manifest,
            ),
        )

    def scratch_sql(self, *, sql: str, limit: int | None = None) -> dict[str, Any]:
        manifest = self._latest_manifest()
        selected_limit = bounded_query_limit(limit or 100)
        return _with_public_run(
            _sanitize_public_value(
                run_scratch_query(
                    manifest=manifest,
                    sql=sql,
                    limit=selected_limit,
                )
            ),
            manifest,
        )

    def gpu_price_index(
        self,
        *,
        family: str | None = None,
        history: bool = False,
        limit: int | None = None,
    ) -> dict[str, Any]:
        manifest = self._latest_manifest()
        selected_limit = bounded_query_limit(limit or 20)
        normalized_family = family.upper() if family else None

        def load() -> dict[str, Any]:
            if history:
                result = query_gold_gpu_price_index_history(
                    lake_root=self.lake_root,
                    history_limit=selected_limit,
                )
            else:
                result = query_gold_gpu_price_index(
                    lake_root=self.lake_root,
                    manifest=manifest,
                )
            rows = result["rows"]
            if normalized_family:
                rows = [
                    row
                    for row in rows
                    if str(row.get("benchmark_family_id") or "").upper()
                    == normalized_family
                ]
            if not history:
                rows = rows[:selected_limit]
            payload = _typed_payload(manifest, rows)
            if history:
                payload["history_run_count"] = result["history_manifest_count"]
            return payload

        return self._cached(
            manifest,
            ("gpu_price_index", normalized_family, history, selected_limit),
            load,
        )

    def gpu_availability(
        self,
        *,
        gpu_model: str | None = None,
        measurement_kind: str | None = None,
        history: bool = False,
        limit: int | None = None,
    ) -> dict[str, Any]:
        manifest = self._latest_manifest()
        selected_limit = bounded_query_limit(limit or 100)
        return self._cached(
            manifest,
            (
                "gpu_availability",
                gpu_model,
                measurement_kind,
                history,
                selected_limit,
            ),
            lambda: _typed_payload(
                manifest,
                query_gold_gpu_availability(
                    lake_root=self.lake_root,
                    gpu_model=gpu_model,
                    measurement_kind=measurement_kind,
                    history=history,
                    limit=selected_limit,
                    manifest=manifest,
                )["rows"],
            ),
        )

    def listings(
        self,
        *,
        gpu_model: str | None = None,
        provider: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        manifest = self._latest_manifest()
        selected_limit = bounded_query_limit(limit or 100)
        return self._cached(
            manifest,
            ("listings", gpu_model, provider, selected_limit),
            lambda: _typed_payload(
                manifest,
                query_gold_listings(
                    lake_root=self.lake_root,
                    gpu_model=gpu_model,
                    provider=provider,
                    limit=selected_limit,
                    manifest=manifest,
                )["rows"],
            ),
        )

    def providers(
        self, *, gpu_model: str | None = None, limit: int | None = None
    ) -> dict[str, Any]:
        manifest = self._latest_manifest()
        selected_limit = bounded_query_limit(limit or 100)
        return self._cached(
            manifest,
            ("providers", gpu_model, selected_limit),
            lambda: _typed_payload(
                manifest,
                query_gold_provider_comparison(
                    lake_root=self.lake_root,
                    gpu_model=gpu_model,
                    limit=selected_limit,
                    manifest=manifest,
                )["rows"],
            ),
        )

    def prime_offers(self, *, family: str | None = None) -> dict[str, Any]:
        manifest = self._latest_manifest()
        normalized_family = family.upper() if family else None

        def load() -> dict[str, Any]:
            result = query_gold_prime_frontier_offer_market(
                lake_root=self.lake_root,
                manifest=manifest,
            )
            filtered: dict[str, Any] = {
                "run": _public_manifest(manifest),
                "current": _family_mapping(result["current"], normalized_family),
                "last_seen": _family_mapping(result["last_seen"], normalized_family),
            }
            for key in ("history", "ladder", "events", "event_history", "offers"):
                filtered[key] = _family_rows(result[key], normalized_family)
            return _sanitize_public_value(filtered)

        return self._cached(
            manifest,
            ("prime_offers", normalized_family),
            load,
        )

    def _latest_manifest(self) -> dict[str, Any]:
        manifest = read_latest_gold_manifest(self.lake_root)
        if not manifest.get("run_id"):
            raise RuntimeError("Latest Gold manifest has no run_id")
        if not manifest.get("table_refs"):
            raise RuntimeError("Latest Gold manifest has no table_refs")
        return manifest

    def _cached(
        self,
        manifest: dict[str, Any],
        operation: tuple[Any, ...],
        loader: Callable[[], Any],
    ) -> Any:
        key = (str(manifest["run_id"]), *operation)
        with self._cache_lock:
            cached = self._cache.get(key)
            if cached is not None:
                self._cache.move_to_end(key)
                return deepcopy(cached)

        value = loader()
        with self._cache_lock:
            self._cache[key] = deepcopy(value)
            self._cache.move_to_end(key)
            while len(self._cache) > self.cache_size:
                self._cache.popitem(last=False)
        return value


def _typed_payload(
    manifest: dict[str, Any], rows: list[dict[str, Any]]
) -> dict[str, Any]:
    public_rows = _sanitize_public_value(rows)
    return {
        "run": _public_manifest(manifest),
        "row_count": len(public_rows),
        "rows": public_rows,
    }


def _with_public_run(
    payload: dict[str, Any], manifest: dict[str, Any]
) -> dict[str, Any]:
    return {"run": _public_manifest(manifest), **payload}


def _public_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        field: deepcopy(manifest.get(field))
        for field in PUBLIC_MANIFEST_FIELDS
        if field in manifest
    }


def _family_rows(
    rows: list[dict[str, Any]], family: str | None
) -> list[dict[str, Any]]:
    if not family:
        return rows
    return [
        row for row in rows if str(row.get("gpu_family_id") or "").upper() == family
    ]


def _family_mapping(
    rows: dict[str, dict[str, Any]], family: str | None
) -> dict[str, dict[str, Any]]:
    if not family:
        return rows
    return {key: value for key, value in rows.items() if key.upper() == family}


def _sanitize_public_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _sanitize_public_value(item)
            for key, item in value.items()
            if key not in PRIVATE_FIELD_NAMES
            and not (isinstance(item, str) and item.startswith("s3://"))
        }
    if isinstance(value, list):
        return [_sanitize_public_value(item) for item in value]
    return value
