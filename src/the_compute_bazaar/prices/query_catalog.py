"""Saved-query catalog backed by packaged DataFusion SQL files."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .datafusion import DataFusionEngine, TableRef
from .sql_models import PACKAGE_ROOT, SQL_ROOT

DEFAULT_QUERY_CATALOG_PATH = SQL_ROOT / "catalog.json"
DEFAULT_QUERY_LIMIT = 100
MAX_QUERY_LIMIT = 1000


@dataclass(frozen=True)
class CatalogQuery:
    query_id: str
    title: str
    description: str
    tables: tuple[str, ...]
    sql_path: Path
    sql: str
    default_limit: int = DEFAULT_QUERY_LIMIT
    engine: str = "datafusion"

    @property
    def query_key(self) -> str:
        return self.query_id

    @property
    def query_hash(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()

    def catalog_entry(self, manifest: dict[str, Any] | None = None) -> dict[str, Any]:
        missing_tables: list[str] = []
        if manifest is None:
            missing_tables = list(self.tables)
        else:
            table_refs = dict(manifest.get("table_refs") or {})
            missing_tables = [
                table for table in self.tables if not table_refs.get(table)
            ]
        return {
            "query_id": self.query_id,
            "query_key": self.query_key,
            "query_hash": self.query_hash,
            "engine": self.engine,
            "title": self.title,
            "description": self.description,
            "tables": list(self.tables),
            "sql_path": _display_sql_path(self.sql_path),
            "default_limit": self.default_limit,
            "available": not missing_tables,
            "missing_tables": missing_tables,
        }


def load_query_catalog(catalog_path: Path | None = None) -> tuple[CatalogQuery, ...]:
    path = catalog_path or DEFAULT_QUERY_CATALOG_PATH
    payload = json.loads(path.read_text(encoding="utf-8"))
    base_dir = path.parent
    engine = str(payload.get("engine") or "datafusion")
    queries: list[CatalogQuery] = []
    for row in payload.get("queries", []):
        sql_path = (base_dir / str(row["sql_path"])).resolve()
        queries.append(
            CatalogQuery(
                query_id=str(row["query_id"]),
                title=str(row["title"]),
                description=str(row.get("description") or ""),
                tables=tuple(str(table) for table in row.get("tables", [])),
                sql_path=sql_path,
                sql=sql_path.read_text(encoding="utf-8").strip().rstrip(";"),
                default_limit=int(row.get("default_limit") or DEFAULT_QUERY_LIMIT),
                engine=engine,
            )
        )
    return tuple(queries)


def get_catalog_query(query_id: str) -> CatalogQuery:
    for query in load_query_catalog():
        if query.query_id == query_id:
            return query
    raise KeyError(f"Unknown saved query: {query_id}")


def list_catalog_queries(
    *, manifest: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    return [query.catalog_entry(manifest) for query in load_query_catalog()]


def run_catalog_query(
    *,
    manifest: dict[str, Any],
    query_id: str,
    limit: int | None = None,
) -> dict[str, Any]:
    query = get_catalog_query(query_id)
    selected_limit = bounded_query_limit(
        limit if limit is not None else query.default_limit
    )
    table_refs = table_refs_for_catalog_query(manifest, query)
    rows = DataFusionEngine(table_refs).query(query.sql, limit=selected_limit)
    return {
        "query": query.catalog_entry(manifest),
        "limit": selected_limit,
        "row_count": len(rows),
        "rows": rows,
    }


def table_refs_for_catalog_query(
    manifest: dict[str, Any], query: CatalogQuery
) -> dict[str, TableRef]:
    manifest_refs = dict(manifest.get("table_refs") or {})
    missing = [table for table in query.tables if not manifest_refs.get(table)]
    if missing:
        raise RuntimeError(
            f"Latest gold manifest is missing table refs for: {', '.join(missing)}"
        )
    return {table: manifest_refs[table] for table in query.tables}


def validate_catalog_sql(sql: str) -> str:
    statement = sql.strip()
    if not statement:
        raise ValueError("SQL is empty")
    return statement


def bounded_query_limit(limit: int) -> int:
    return max(1, min(MAX_QUERY_LIMIT, int(limit)))


def _display_sql_path(path: Path) -> str:
    try:
        return str(path.relative_to(PACKAGE_ROOT))
    except ValueError:
        return str(path)
