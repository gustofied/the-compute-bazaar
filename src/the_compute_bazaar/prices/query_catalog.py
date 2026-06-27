"""Curia query catalog backed by versioned DataFusion SQL files."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .datafusion import query_tables


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_QUERY_CATALOG_DIR = PROJECT_ROOT / "queries" / "curia"
DEFAULT_QUERY_CATALOG_PATH = DEFAULT_QUERY_CATALOG_DIR / "catalog.json"
DEFAULT_QUERY_LIMIT = 100
MAX_QUERY_LIMIT = 1000
SCRATCH_QUERY_ID = "scratch_sql"
SCRATCH_QUERY_VERSION = "adhoc"
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


@dataclass(frozen=True)
class CatalogQuery:
    query_id: str
    version: str
    title: str
    description: str
    tables: tuple[str, ...]
    sql_path: Path
    sql: str
    default_limit: int = DEFAULT_QUERY_LIMIT
    engine: str = "datafusion"

    @property
    def query_key(self) -> str:
        return f"{self.query_id}:{self.version}"

    @property
    def query_hash(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()

    def catalog_entry(self, manifest: dict[str, Any] | None = None) -> dict[str, Any]:
        missing_tables: list[str] = []
        if manifest is None:
            missing_tables = list(self.tables)
        else:
            table_refs = dict(manifest.get("table_refs") or {})
            missing_tables = [table for table in self.tables if not table_refs.get(table)]
        return {
            "query_id": self.query_id,
            "version": self.version,
            "query_key": self.query_key,
            "query_hash": self.query_hash,
            "engine": self.engine,
            "title": self.title,
            "description": self.description,
            "tables": list(self.tables),
            "sql_path": str(self.sql_path.relative_to(PROJECT_ROOT)),
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
                version=str(row.get("version") or "v0"),
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


def get_catalog_query(query_id: str, *, version: str | None = None) -> CatalogQuery:
    matches = [query for query in load_query_catalog() if query.query_id == query_id]
    if version:
        matches = [query for query in matches if query.version == version]
    if not matches:
        suffix = f" version {version}" if version else ""
        raise KeyError(f"Unknown Curia query: {query_id}{suffix}")
    return sorted(matches, key=lambda query: query.version, reverse=True)[0]


def list_catalog_queries(*, manifest: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    return [query.catalog_entry(manifest) for query in load_query_catalog()]


def run_catalog_query(
    *,
    manifest: dict[str, Any],
    query_id: str,
    version: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    query = get_catalog_query(query_id, version=version)
    selected_limit = bounded_query_limit(limit if limit is not None else query.default_limit)
    table_refs = table_refs_for_catalog_query(manifest, query)
    rows = query_tables(
        tables=table_refs,
        sql=with_limit(query.sql, selected_limit),
    )
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
    selected_limit = bounded_query_limit(limit if limit is not None else DEFAULT_QUERY_LIMIT)
    table_refs = scratch_table_refs(manifest)
    rows = query_tables(
        tables=table_refs,
        sql=with_scratch_limit(cleaned_sql, selected_limit),
    )
    return {
        "query": scratch_query_entry(manifest, cleaned_sql),
        "limit": selected_limit,
        "row_count": len(rows),
        "rows": rows,
    }


def scratch_query_entry(manifest: dict[str, Any], sql: str | None = None) -> dict[str, Any]:
    table_names = sorted(scratch_table_refs(manifest))
    entry: dict[str, Any] = {
        "query_id": SCRATCH_QUERY_ID,
        "version": SCRATCH_QUERY_VERSION,
        "query_key": f"{SCRATCH_QUERY_ID}:{SCRATCH_QUERY_VERSION}",
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
        if ref and (table_name.startswith("fact_") or table_name.startswith("dim_"))
    }


def table_refs_for_catalog_query(manifest: dict[str, Any], query: CatalogQuery) -> dict[str, str]:
    manifest_refs = dict(manifest.get("table_refs") or {})
    missing = [table for table in query.tables if not manifest_refs.get(table)]
    if missing:
        raise RuntimeError(f"Latest gold manifest is missing table refs for: {', '.join(missing)}")
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
    return f"{statement[:limit_match.start()].rstrip()}\nlimit {clamped_limit}"


def validate_scratch_sql(sql: str) -> str:
    cleaned = _strip_sql_comments(sql).strip()
    if not cleaned:
        raise ValueError("Scratch SQL is empty")

    statements = [statement.strip() for statement in cleaned.split(";") if statement.strip()]
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
        raise ValueError(f"Scratch SQL is read-only; forbidden token: {forbidden_tokens[0]}")
    forbidden_functions = sorted(tokens & FORBIDDEN_SCRATCH_SQL_FUNCTIONS)
    if forbidden_functions:
        raise ValueError(f"Scratch SQL cannot read external files or object paths: {forbidden_functions[0]}")
    return statement


def bounded_query_limit(limit: int) -> int:
    return max(1, min(MAX_QUERY_LIMIT, int(limit)))


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
