"""Saved-query catalog backed by packaged DataFusion SQL files."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .datafusion import DataFusionEngine
from .sql_models import PACKAGE_ROOT, SQL_ROOT

PROJECT_ROOT = PACKAGE_ROOT.parents[1]
DEFAULT_QUERY_CATALOG_DIR = SQL_ROOT
DEFAULT_QUERY_CATALOG_PATH = SQL_ROOT / "catalog.json"
DEFAULT_QUERY_LIMIT = 100
MAX_QUERY_LIMIT = 1000
SCRATCH_QUERY_ID = "scratch_sql"
READ_ONLY_SQL_PREFIXES = {"select", "with"}
FORBIDDEN_SCRATCH_SQL_TOKENS = {
    "alter",
    "attach",
    "copy",
    "create",
    "delete",
    "detach",
    "drop",
    "insert",
    "load",
    "replace",
    "truncate",
    "update",
    "vacuum",
}
FORBIDDEN_SCRATCH_SQL_FUNCTIONS = {
    "read_csv",
    "read_json",
    "read_ndjson",
    "read_parquet",
}
FORBIDDEN_SCRATCH_SQL_IDENTIFIERS = {
    "bronze_refs",
    "manifest_ref",
    "raw_ref",
    "silver_refs",
    "source_manifest_ref",
    "source_normalized_ref",
    "table_refs",
}
SCRATCH_TABLE_ALLOWLIST = {
    "dim_gpu_products",
    "dim_providers",
    "dim_sources",
    "fact_gpu_price_index",
    "fact_gpu_price_index_constituents",
    "fact_compute_market_state",
    "fact_compute_market_state_history",
    "fact_gpu_listings",
    "fact_gpu_availability",
    "fact_gpu_availability_history",
    "fact_prime_frontier_offer_events",
    "fact_prime_frontier_offer_history",
    "fact_prime_frontier_offer_ladder",
    "fact_prime_frontier_offer_reference_history",
}


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
    rows = DataFusionEngine(table_refs).query(with_limit(query.sql, selected_limit))
    return {
        "query": query.catalog_entry(manifest),
        "limit": selected_limit,
        "row_count": len(rows),
        "rows": rows,
    }


def run_scratch_query(
    *,
    manifest: dict[str, Any],
    sql: str,
    limit: int | None = None,
) -> dict[str, Any]:
    cleaned_sql = validate_scratch_sql(sql)
    selected_limit = bounded_query_limit(
        limit if limit is not None else DEFAULT_QUERY_LIMIT
    )
    table_refs = scratch_table_refs(manifest)
    rows = DataFusionEngine(table_refs).query(
        with_scratch_limit(cleaned_sql, selected_limit)
    )
    return {
        "query": scratch_query_entry(manifest, cleaned_sql),
        "limit": selected_limit,
        "row_count": len(rows),
        "rows": rows,
    }


def scratch_query_entry(
    manifest: dict[str, Any], sql: str | None = None
) -> dict[str, Any]:
    table_names = sorted(scratch_table_refs(manifest))
    entry: dict[str, Any] = {
        "query_id": SCRATCH_QUERY_ID,
        "query_key": SCRATCH_QUERY_ID,
        "engine": "datafusion",
        "title": "Scratch SQL",
        "description": "Read-only ad hoc SQL over latest gold tables.",
        "tables": table_names,
        "default_limit": DEFAULT_QUERY_LIMIT,
        "max_limit": MAX_QUERY_LIMIT,
        "available": bool(table_names),
        "missing_tables": [],
        "read_only": True,
    }
    if sql is not None:
        entry["query_hash"] = hashlib.sha256(sql.encode("utf-8")).hexdigest()
    return entry


def scratch_table_refs(manifest: dict[str, Any]) -> dict[str, str]:
    table_refs = dict(manifest.get("table_refs") or {})
    return {
        table_name: str(ref)
        for table_name, ref in table_refs.items()
        if ref and table_name in SCRATCH_TABLE_ALLOWLIST
    }


def table_refs_for_catalog_query(
    manifest: dict[str, Any], query: CatalogQuery
) -> dict[str, str]:
    manifest_refs = dict(manifest.get("table_refs") or {})
    missing = [table for table in query.tables if not manifest_refs.get(table)]
    if missing:
        raise RuntimeError(
            f"Latest gold manifest is missing table refs for: {', '.join(missing)}"
        )
    return {table: str(manifest_refs[table]) for table in query.tables}


def with_limit(sql: str, limit: int) -> str:
    return f"{sql.strip().rstrip(';')}\nlimit {limit}"


def with_scratch_limit(sql: str, limit: int) -> str:
    statement = sql.strip().rstrip(";")
    masked = _mask_sql_string_literals(statement)
    limit_match = re.search(r"\blimit\s+(\d+)\s*$", masked, flags=re.IGNORECASE)
    if not limit_match:
        return f"{statement}\nlimit {limit}"

    requested_limit = int(limit_match.group(1))
    clamped_limit = min(requested_limit, limit)
    return f"{statement[: limit_match.start()].rstrip()}\nlimit {clamped_limit}"


def validate_scratch_sql(sql: str) -> str:
    return _validate_read_only_sql(
        sql,
        forbidden_identifiers=FORBIDDEN_SCRATCH_SQL_IDENTIFIERS,
    )


def validate_catalog_sql(sql: str) -> str:
    return _validate_read_only_sql(sql, forbidden_identifiers=set())


def _validate_read_only_sql(
    sql: str,
    *,
    forbidden_identifiers: set[str],
) -> str:
    cleaned = _strip_sql_comments(sql).strip()
    if not cleaned:
        raise ValueError("Scratch SQL is empty")

    statements = [
        statement.strip() for statement in cleaned.split(";") if statement.strip()
    ]
    if len(statements) != 1:
        raise ValueError("Scratch SQL must contain exactly one read-only statement")

    statement = statements[0].rstrip(";").strip()
    first_token_match = re.match(r"[A-Za-z_][A-Za-z0-9_]*", statement)
    first_token = first_token_match.group(0).lower() if first_token_match else ""
    if first_token not in READ_ONLY_SQL_PREFIXES:
        raise ValueError("Scratch SQL must start with SELECT or WITH")

    token_source = _mask_sql_string_literals(statement.lower())
    tokens = set(re.findall(r"\b[a-z_][a-z0-9_]*\b", token_source))
    forbidden_tokens = sorted(tokens & FORBIDDEN_SCRATCH_SQL_TOKENS)
    if forbidden_tokens:
        raise ValueError(
            f"Scratch SQL is read-only; forbidden token: {forbidden_tokens[0]}"
        )
    forbidden_functions = sorted(tokens & FORBIDDEN_SCRATCH_SQL_FUNCTIONS)
    if forbidden_functions:
        raise ValueError(
            f"Scratch SQL cannot read external files or object paths: {forbidden_functions[0]}"
        )
    blocked_identifiers = sorted(tokens & forbidden_identifiers)
    if blocked_identifiers:
        raise ValueError(
            f"Scratch SQL cannot read private evidence fields: {blocked_identifiers[0]}"
        )
    return statement


def bounded_query_limit(limit: int) -> int:
    return max(1, min(MAX_QUERY_LIMIT, int(limit)))


def _display_sql_path(path: Path) -> str:
    try:
        return str(path.relative_to(PACKAGE_ROOT))
    except ValueError:
        return str(path)


def _strip_sql_comments(sql: str) -> str:
    without_block_comments = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    return re.sub(r"--[^\n\r]*", "", without_block_comments)


def _mask_sql_string_literals(sql: str) -> str:
    result: list[str] = []
    quote: str | None = None
    index = 0
    while index < len(sql):
        char = sql[index]
        if quote is None:
            if char in {"'", '"'}:
                quote = char
                result.append(" ")
            else:
                result.append(char)
            index += 1
            continue

        if char == quote:
            if index + 1 < len(sql) and sql[index + 1] == quote:
                result.extend("  ")
                index += 2
                continue
            quote = None
        result.append(" ")
        index += 1
    return "".join(result)
