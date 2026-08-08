"""Typed commands shared by the Terminal shell and its workspaces."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Literal

from pydantic import BaseModel, Field

from ..prices.query_catalog import MAX_QUERY_LIMIT


CommandKind = Literal[
    "help",
    "clear",
    "navigate",
    "locked",
    "status",
    "catalog",
    "view",
    "query",
    "table",
    "describe",
    "sql",
    "error",
]


@dataclass(frozen=True)
class TerminalCommand:
    command: str
    description: str
    workspace: Literal["terminal", "data", "eval", "trade"] = "terminal"

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


class TerminalCommandRequest(BaseModel):
    command: str = Field(min_length=1, max_length=10_000)


class TerminalAction(BaseModel):
    kind: CommandKind
    href: str | None = None
    section: str | None = None
    view_id: str | None = None
    query_id: str | None = None
    table_ref: str | None = None
    sql: str | None = None
    limit: int | None = None
    message: str | None = None


COMMANDS = (
    TerminalCommand("data", "Open the Data workspace."),
    TerminalCommand("eval", "Open the Eval workspace."),
    TerminalCommand("home", "Return to the Terminal menu."),
    TerminalCommand("status", "Show the active lake run and workspaces."),
    TerminalCommand("tables", "Open the Silver and Gold catalog.", "data"),
    TerminalCommand("views", "Open curated market views.", "data"),
    TerminalCommand("queries", "Open saved SQL queries.", "data"),
    TerminalCommand(
        "view gpu-index-history",
        "Open a curated Perspective view.",
        "data",
    ),
    TerminalCommand(
        "query gpu_price_index_history",
        "Run a saved DataFusion query.",
        "data",
    ),
    TerminalCommand(
        "table gold.fact_gpu_price_index",
        "Inspect a Silver or Gold table.",
        "data",
    ),
    TerminalCommand(
        "describe gold.fact_gpu_price_index",
        "Inspect a table schema.",
        "data",
    ),
    TerminalCommand(
        "select * from gold.fact_gpu_price_index",
        "Run bounded read-only SQL.",
        "data",
    ),
)


def command_catalog() -> list[dict[str, str]]:
    return [command.as_dict() for command in COMMANDS]


def resolve_command(raw: str) -> TerminalAction:
    command = _strip_cli_prefix(raw)
    if not command:
        return _error("Enter a command or read-only SQL.")
    if re.match(r"^(select|with)\b", command, flags=re.IGNORECASE):
        return TerminalAction(kind="sql", sql=command, limit=500)

    match = re.match(r"^(\S+)(?:\s+([\s\S]*))?$", command)
    verb = (match.group(1) if match else "").lower()
    argument = (match.group(2) if match and match.group(2) else "").strip()

    if verb in {"?", "help"}:
        return TerminalAction(kind="help")
    if verb in {"home", "menu", "terminal"}:
        return TerminalAction(kind="navigate", href="/")
    if verb == "data":
        return TerminalAction(kind="navigate", href="/data")
    if verb in {"eval", "evals"}:
        return TerminalAction(kind="navigate", href="/eval")
    if verb == "trade":
        return TerminalAction(kind="locked")
    if verb == "status":
        return TerminalAction(kind="status")
    if verb == "clear":
        return TerminalAction(kind="clear")
    if verb in {"tables", "catalog"}:
        return TerminalAction(kind="catalog", section="tables")
    if verb == "queries":
        return TerminalAction(kind="catalog", section="queries")
    if verb == "views":
        return TerminalAction(kind="catalog", section="views")
    if verb == "view":
        return (
            TerminalAction(kind="view", view_id=argument)
            if argument
            else _error("Use view <view_id>.")
        )
    if verb == "query":
        limit, query_id = _parse_limit(argument)
        return (
            TerminalAction(kind="query", query_id=query_id, limit=limit)
            if query_id
            else _error("Use query <query_id>.")
        )
    if verb in {"table", "open"}:
        return (
            TerminalAction(kind="table", table_ref=argument)
            if argument
            else _error("Use table silver.<name> or table gold.<name>.")
        )
    if verb in {"describe", "schema"}:
        return (
            TerminalAction(kind="describe", table_ref=argument)
            if argument
            else _error("Use describe silver.<name> or describe gold.<name>.")
        )
    if verb == "sql":
        limit, statement = _parse_limit(argument)
        statement = _strip_outer_quotes(statement)
        if re.match(r"^(select|with)\b", statement, flags=re.IGNORECASE):
            return TerminalAction(kind="sql", sql=statement, limit=limit)
        return _error("SQL must start with SELECT or WITH.")
    return _error(f"Unknown command: {verb}. Try help.")


def _strip_cli_prefix(value: str) -> str:
    command = value.strip()
    command = re.sub(
        r"^compute-bazaar(?:\s+terminal)?(?:\s+|$)",
        "",
        command,
        flags=re.IGNORECASE,
    )
    return command.removeprefix("/").strip()


def _strip_outer_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _parse_limit(value: str, fallback: int = 500) -> tuple[int, str]:
    match = re.match(r"^--limit\s+(\d+)\s+([\s\S]+)$", value, flags=re.IGNORECASE)
    if not match:
        return fallback, value
    limit = max(1, min(MAX_QUERY_LIMIT, int(match.group(1))))
    return limit, match.group(2).strip()


def _error(message: str) -> TerminalAction:
    return TerminalAction(kind="error", message=message)
