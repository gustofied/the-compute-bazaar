"""DataFusion-backed viewport access for one large Perspective table."""

from __future__ import annotations

import math
from typing import Any, Literal

import pyarrow as pa
from pydantic import BaseModel, Field

from ..data_catalog import ComputeBazaarCatalog


VIRTUAL_TABLE_REF = "gold.fact_gpu_availability_history"
MAX_VIEWPORT_ROWS = 2_000


class VirtualViewConfig(BaseModel):
    table: Literal["gold.fact_gpu_availability_history"] = VIRTUAL_TABLE_REF
    columns: list[str | None] = Field(default_factory=list)
    filter: list[tuple[str, str, Any]] = Field(default_factory=list)
    filter_op: Literal["and", "or"] = "and"
    sort: list[tuple[str, str]] = Field(default_factory=list)
    group_by: list[str] = Field(default_factory=list)
    split_by: list[str] = Field(default_factory=list)
    expressions: dict[str, str] = Field(default_factory=dict)


class VirtualDataRequest(VirtualViewConfig):
    start_row: int = Field(default=0, ge=0)
    end_row: int = Field(default=100, ge=1)


class DataFusionVirtualTable:
    """Translate a small Perspective view contract into DataFusion SQL."""

    def __init__(self, catalog: ComputeBazaarCatalog) -> None:
        description = catalog.describe(VIRTUAL_TABLE_REF)
        self.catalog = catalog
        self.columns = {
            str(column["column_name"]): str(column["data_type"])
            for column in description["columns"]
        }

    def schema(self) -> dict[str, str]:
        return {
            column: _perspective_type(data_type)
            for column, data_type in self.columns.items()
        }

    def size(self, config: VirtualViewConfig) -> int:
        where = self._where(config)
        row = self.catalog.engine.query(
            f"select count(*) as row_count from {VIRTUAL_TABLE_REF}{where}"
        )[0]
        return int(row["row_count"])

    def data(self, request: VirtualDataRequest) -> pa.Table:
        if request.end_row <= request.start_row:
            raise ValueError("Viewport end must be greater than its start")
        row_count = request.end_row - request.start_row
        if row_count > MAX_VIEWPORT_ROWS:
            raise ValueError(
                f"Viewport cannot exceed {MAX_VIEWPORT_ROWS:,} rows"
            )
        selected = [column for column in request.columns if column is not None]
        if not selected:
            selected = list(self.columns)
        self._columns(selected)
        select_sql = ", ".join(self._select(column) for column in selected)
        sql = (
            f"select {select_sql} from {VIRTUAL_TABLE_REF}"
            f"{self._where(request)}{self._order(request)} "
            f"limit {row_count} offset {request.start_row}"
        )
        return self.catalog.engine.query_arrow(sql)

    def _where(self, config: VirtualViewConfig) -> str:
        self._flat(config)
        if not config.filter:
            return ""
        filters = [
            self._filter(column, operator, value)
            for column, operator, value in config.filter
        ]
        joiner = f" {config.filter_op} "
        return f" where {joiner.join(filters)}"

    def _order(self, config: VirtualViewConfig) -> str:
        clauses: list[str] = []
        for column, direction in config.sort:
            self._column(column)
            normalized = direction.strip().lower()
            if normalized not in {"asc", "desc", "col asc", "col desc"}:
                raise ValueError(f"Unsupported sort direction: {direction}")
            clauses.append(f'{_identifier(column)} {normalized.removeprefix("col ")}')
        if "observation_id" in self.columns and not any(
            column == "observation_id" for column, _ in config.sort
        ):
            clauses.append('"observation_id" asc')
        return f" order by {', '.join(clauses)}" if clauses else ""

    def _filter(self, column: str, operator: str, value: Any) -> str:
        self._column(column)
        identifier = _identifier(column)
        normalized = operator.strip().lower()
        if normalized in {"is null", "is not null"}:
            return f"{identifier} {normalized}"
        if normalized in {"==", "!="} and value is None:
            return f"{identifier} is {'not ' if normalized == '!=' else ''}null"
        if normalized in {"in", "not in"}:
            if not isinstance(value, list) or not value:
                raise ValueError(f"{operator} requires a non-empty list")
            values = ", ".join(_literal(item) for item in value)
            return f"{identifier} {normalized} ({values})"
        sql_operator = {
            "==": "=",
            "!=": "!=",
            ">": ">",
            ">=": ">=",
            "<": "<",
            "<=": "<=",
            "like": "like",
            "is distinct from": "is distinct from",
            "is not distinct from": "is not distinct from",
        }.get(normalized)
        if not sql_operator:
            raise ValueError(f"Unsupported filter operator: {operator}")
        return f"{identifier} {sql_operator} {_literal(value)}"

    def _select(self, column: str) -> str:
        identifier = _identifier(column)
        if self.columns[column].lower() == "null":
            return f"cast({identifier} as varchar) as {identifier}"
        return identifier

    def _flat(self, config: VirtualViewConfig) -> None:
        if config.group_by or config.split_by or config.expressions:
            raise ValueError("This virtual table currently supports flat views only")

    def _columns(self, columns: list[str]) -> None:
        for column in columns:
            self._column(column)

    def _column(self, column: str) -> None:
        if column not in self.columns:
            raise ValueError(f"Unknown availability column: {column}")


def _identifier(value: str) -> str:
    return f'"{value.replace(chr(34), chr(34) * 2)}"'


def _literal(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Filter numbers must be finite")
        return repr(value)
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    raise ValueError(f"Unsupported filter value: {type(value).__name__}")


def _perspective_type(data_type: str) -> str:
    normalized = data_type.lower()
    if normalized.startswith("timestamp"):
        return "datetime"
    if normalized.startswith("date"):
        return "date"
    if "int" in normalized:
        return "integer"
    if any(name in normalized for name in ("float", "double", "decimal")):
        return "float"
    if normalized.startswith("bool"):
        return "boolean"
    return "string"
