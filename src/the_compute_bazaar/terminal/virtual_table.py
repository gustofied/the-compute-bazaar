"""DataFusion-backed viewport access for one large Perspective table."""

from __future__ import annotations

import math
from datetime import UTC, date, datetime
from typing import Any, Literal

import pyarrow as pa
from pydantic import BaseModel, ConfigDict, Field

from ..data_catalog import ComputeBazaarCatalog


VIRTUAL_TABLE_REF = "gold.fact_gpu_availability_history"
MAX_VIEWPORT_ROWS = 2_000
MAX_COLUMNS = 128
MAX_FILTERS = 64
MAX_FILTER_VALUES = 256
MAX_SORTS = 32
Aggregate = Literal["count", "sum", "avg", "min", "max"]


class VirtualViewConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    table: Literal["gold.fact_gpu_availability_history"] = VIRTUAL_TABLE_REF
    columns: list[str | None] = Field(default_factory=list, max_length=MAX_COLUMNS)
    filter: list[tuple[str, str, Any]] = Field(
        default_factory=list, max_length=MAX_FILTERS
    )
    filter_op: Literal["and", "or"] = "and"
    sort: list[tuple[str, str]] = Field(default_factory=list, max_length=MAX_SORTS)
    group_by: list[str] = Field(default_factory=list, max_length=MAX_COLUMNS)
    group_rollup_mode: Literal["flat"] = "flat"
    aggregates: dict[str, Aggregate] = Field(
        default_factory=dict, max_length=MAX_COLUMNS
    )
    split_by: list[str] = Field(default_factory=list, max_length=MAX_COLUMNS)
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
        self._validate(config)
        where = self._where(config)
        if config.group_by:
            groups = ", ".join(_identifier(column) for column in config.group_by)
            source = (
                f"(select {groups} from {VIRTUAL_TABLE_REF}{where} "
                f"group by {groups}) as grouped"
            )
        else:
            source = f"{VIRTUAL_TABLE_REF}{where}"
        row = self.catalog.engine.query(f"select count(*) as row_count from {source}")[
            0
        ]
        return int(row["row_count"])

    def data(self, request: VirtualDataRequest) -> pa.Table:
        if request.end_row <= request.start_row:
            raise ValueError("Viewport end must be greater than its start")
        row_count = request.end_row - request.start_row
        if row_count > MAX_VIEWPORT_ROWS:
            raise ValueError(f"Viewport cannot exceed {MAX_VIEWPORT_ROWS:,} rows")
        self._validate(request)
        selected = self._selected(request)
        if request.group_by:
            group_select = [
                f'{_identifier(column)} as "__ROW_PATH_{index}__"'
                for index, column in enumerate(request.group_by)
            ]
            value_select = [
                self._aggregate_select(column, request) for column in selected
            ]
            select_sql = ", ".join([*group_select, *value_select])
            groups = ", ".join(_identifier(column) for column in request.group_by)
            group_sql = f" group by {groups}"
        else:
            select_sql = ", ".join(self._select(column) for column in selected)
            group_sql = ""
        sql = (
            f"select {select_sql} from {VIRTUAL_TABLE_REF}"
            f"{self._where(request)}{group_sql}{self._order(request, selected)} "
            f"limit {row_count} offset {request.start_row}"
        )
        return _perspective_arrow(self.catalog.engine.query_arrow(sql))

    def _where(self, config: VirtualViewConfig) -> str:
        if not config.filter:
            return ""
        filters = [
            self._filter(column, operator, value)
            for column, operator, value in config.filter
        ]
        joiner = f" {config.filter_op} "
        return f" where {joiner.join(filters)}"

    def _order(self, config: VirtualViewConfig, selected: list[str]) -> str:
        clauses: list[str] = []
        sorted_columns: set[str] = set()
        for column, direction in config.sort:
            self._column(column)
            normalized = direction.strip().lower()
            if normalized == "none":
                continue
            absolute = normalized.endswith(" abs")
            normalized = normalized.removeprefix("col ").removesuffix(" abs")
            if normalized not in {"asc", "desc"}:
                raise ValueError(f"Unsupported sort direction: {direction}")
            if config.group_by and column not in config.group_by:
                expression = (
                    _identifier(column)
                    if column in selected
                    else self._aggregate_expression(column, config)
                )
                result_type = self._aggregate_type(column, config)
            else:
                expression = _identifier(column)
                result_type = _perspective_type(self.columns[column])
            if absolute:
                if result_type not in {"integer", "float"}:
                    raise ValueError(f"Absolute sort requires a number: {column}")
                expression = f"abs({expression})"
            clauses.append(f"{expression} {normalized}")
            sorted_columns.add(column)
        if config.group_by:
            clauses.extend(
                f'"__ROW_PATH_{index}__" asc'
                for index, column in enumerate(config.group_by)
                if column not in sorted_columns
            )
        elif (
            "observation_id" in self.columns and "observation_id" not in sorted_columns
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
            if len(value) > MAX_FILTER_VALUES:
                raise ValueError(
                    f"{operator} cannot exceed {MAX_FILTER_VALUES:,} values"
                )
            values = ", ".join(
                _typed_literal(item, self.columns[column]) for item in value
            )
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
        return (
            f"{identifier} {sql_operator} {_typed_literal(value, self.columns[column])}"
        )

    def _select(self, column: str) -> str:
        identifier = _identifier(column)
        if self.columns[column].lower() == "null":
            return f"cast({identifier} as varchar) as {identifier}"
        return identifier

    def _selected(self, config: VirtualViewConfig) -> list[str]:
        requested = [column for column in config.columns if column is not None]
        if config.group_by:
            selected = [column for column in requested if column not in config.group_by]
        else:
            selected = requested or list(self.columns)
        self._columns(selected)
        return selected

    def _aggregate_select(self, column: str, config: VirtualViewConfig) -> str:
        return f"{self._aggregate_expression(column, config)} as {_identifier(column)}"

    def _aggregate_expression(self, column: str, config: VirtualViewConfig) -> str:
        aggregate = self._aggregate(column, config)
        return f"{aggregate}({_identifier(column)})"

    def _aggregate(self, column: str, config: VirtualViewConfig) -> Aggregate:
        aggregate = config.aggregates.get(column)
        if aggregate is None:
            aggregate = (
                "sum"
                if _perspective_type(self.columns[column]) in {"integer", "float"}
                else "count"
            )
        self._validate_aggregate(column, aggregate)
        return aggregate

    def _aggregate_type(self, column: str, config: VirtualViewConfig) -> str:
        aggregate = self._aggregate(column, config)
        if aggregate == "count":
            return "integer"
        if aggregate == "avg":
            return "float"
        return _perspective_type(self.columns[column])

    def _validate(self, config: VirtualViewConfig) -> None:
        if config.split_by:
            raise ValueError("Split by is not supported yet")
        if config.expressions:
            raise ValueError("Expressions are not supported yet")
        if len(config.group_by) != len(set(config.group_by)):
            raise ValueError("Group by columns must be unique")
        self._columns(config.group_by)
        self._columns([column for column, _ in config.sort])
        self._selected(config)
        for column, aggregate in config.aggregates.items():
            self._column(column)
            self._validate_aggregate(column, aggregate)

    def _validate_aggregate(self, column: str, aggregate: Aggregate) -> None:
        column_type = _perspective_type(self.columns[column])
        if aggregate in {"sum", "avg"} and column_type not in {"integer", "float"}:
            raise ValueError(f"{aggregate} requires a numeric column: {column}")
        if aggregate in {"min", "max"} and column_type == "boolean":
            raise ValueError(
                f"{aggregate} is not supported for boolean column: {column}"
            )

    def _columns(self, columns: list[str]) -> None:
        for column in columns:
            self._column(column)

    def _column(self, column: str) -> None:
        if column not in self.columns:
            raise ValueError(f"Unknown availability column: {column}")


def _identifier(value: str) -> str:
    return f'"{value.replace(chr(34), chr(34) * 2)}"'


def _perspective_arrow(table: pa.Table) -> pa.Table:
    fields = [
        pa.field(
            field.name,
            pa.timestamp("ms", tz=field.type.tz)
            if pa.types.is_timestamp(field.type)
            else field.type,
            nullable=field.nullable,
            metadata=field.metadata,
        )
        for field in table.schema
    ]
    schema = pa.schema(fields, metadata=table.schema.metadata)
    return table if schema == table.schema else table.cast(schema, safe=False)


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


def _typed_literal(value: Any, data_type: str) -> str:
    if value is None:
        return "null"
    normalized = data_type.lower()
    if normalized.startswith("timestamp"):
        return f"to_timestamp_millis({_timestamp_millis(value)})"
    if normalized.startswith("date"):
        return f"date '{_date_value(value).isoformat()}'"
    return _literal(value)


def _timestamp_millis(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError(
            "Datetime filters require an ISO timestamp or epoch milliseconds"
        )
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)):
            raise ValueError("Datetime filters must be finite")
        return int(value)
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"Invalid datetime filter: {value}") from exc
    else:
        raise ValueError(
            "Datetime filters require an ISO timestamp or epoch milliseconds"
        )
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.timestamp() * 1_000)


def _date_value(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(float(value)):
            raise ValueError("Date filters must be finite")
        return datetime.fromtimestamp(float(value) / 1_000, UTC).date()
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError as exc:
            raise ValueError(f"Invalid date filter: {value}") from exc
    raise ValueError("Date filters require an ISO date or epoch milliseconds")


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
