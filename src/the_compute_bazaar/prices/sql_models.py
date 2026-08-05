"""Load and render packaged DataFusion SQL assets."""

from __future__ import annotations

import hashlib
from pathlib import Path
from string import Template
from typing import Any


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SQL_ROOT = PACKAGE_ROOT / "sql"
SQL_MODELS_ROOT = SQL_ROOT / "models"
SQL_QUERIES_ROOT = SQL_ROOT / "queries"


def read_sql(relative_path: str) -> str:
    path = _sql_path(relative_path)
    return path.read_text(encoding="utf-8").strip().rstrip(";")


def render_sql(
    relative_path: str,
    context: dict[str, Any] | None = None,
    *,
    fragments: dict[str, str] | None = None,
) -> str:
    template = Template(read_sql(relative_path))
    rendered_context = {
        name: _sql_literal(str(value)) for name, value in (context or {}).items()
    }
    for name, fragment in (fragments or {}).items():
        if name in rendered_context:
            raise ValueError(
                f"SQL template value {name!r} is both a literal and fragment"
            )
        rendered_context[name] = fragment
    try:
        return template.substitute(rendered_context)
    except KeyError as exc:
        raise KeyError(
            f"SQL model {relative_path} requires context value {exc.args[0]!r}"
        ) from exc


def sql_metadata(relative_path: str) -> dict[str, str]:
    sql = read_sql(relative_path)
    return {
        "path": f"sql/{relative_path}",
        "sha256": hashlib.sha256(sql.encode("utf-8")).hexdigest(),
    }


def _sql_path(relative_path: str) -> Path:
    path = (SQL_ROOT / relative_path).resolve()
    if SQL_ROOT.resolve() != path and SQL_ROOT.resolve() not in path.parents:
        raise ValueError(f"SQL path escapes the packaged SQL root: {relative_path}")
    if not path.is_file():
        raise FileNotFoundError(f"SQL asset does not exist: {relative_path}")
    return path


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
