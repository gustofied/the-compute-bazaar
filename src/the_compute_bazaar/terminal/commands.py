"""Typed commands shared by the Terminal shell and its workspaces."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field

from ..prices.query_catalog import MAX_QUERY_LIMIT


class TerminalCommandRequest(BaseModel):
    command: str = Field(min_length=1, max_length=10_000)


class _Action(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HelpAction(_Action):
    kind: Literal["help"] = "help"


class ClearAction(_Action):
    kind: Literal["clear"] = "clear"


class NavigateAction(_Action):
    kind: Literal["navigate"] = "navigate"
    href: str


class LockedAction(_Action):
    kind: Literal["locked"] = "locked"


class StatusAction(_Action):
    kind: Literal["status"] = "status"


class CatalogAction(_Action):
    kind: Literal["catalog"] = "catalog"
    section: Literal["tables", "queries", "views", "models", "blueprints"]


class ViewAction(_Action):
    kind: Literal["view"] = "view"
    view_id: str


class QueryAction(_Action):
    kind: Literal["query"] = "query"
    query_id: str
    limit: int


class ModelAction(_Action):
    kind: Literal["model"] = "model"
    model_id: str


class BlueprintAction(_Action):
    kind: Literal["blueprint"] = "blueprint"
    blueprint_id: str


class TableAction(_Action):
    kind: Literal["table"] = "table"
    table_ref: str


class DescribeAction(_Action):
    kind: Literal["describe"] = "describe"
    table_ref: str


class SqlAction(_Action):
    kind: Literal["sql"] = "sql"
    sql: str
    limit: int
    perspective: dict[str, Any] | None = None


class ShellAction(_Action):
    kind: Literal["shell"] = "shell"
    command: str


class ErrorAction(_Action):
    kind: Literal["error"] = "error"
    message: str


TerminalAction: TypeAlias = Annotated[
    HelpAction
    | ClearAction
    | NavigateAction
    | LockedAction
    | StatusAction
    | CatalogAction
    | ViewAction
    | QueryAction
    | ModelAction
    | BlueprintAction
    | TableAction
    | DescribeAction
    | SqlAction
    | ShellAction
    | ErrorAction,
    Field(discriminator="kind"),
]

CommandHandler: TypeAlias = Callable[[str], TerminalAction]


@dataclass(frozen=True)
class TerminalCommand:
    name: str
    syntax: str
    description: str
    handler: CommandHandler
    workspace: Literal["terminal", "data", "eval", "trade"] = "terminal"
    aliases: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, str]:
        return {
            "command": self.syntax,
            "description": self.description,
            "workspace": self.workspace,
        }


def _no_argument(action: TerminalAction) -> CommandHandler:
    def handler(_: str) -> TerminalAction:
        return action

    return handler


def _view(argument: str) -> TerminalAction:
    return ViewAction(view_id=argument) if argument else _error("Use view <view_id>.")


def _query(argument: str) -> TerminalAction:
    limit, query_id = _parse_limit(argument)
    return (
        QueryAction(query_id=query_id, limit=limit)
        if query_id
        else _error("Use query <query_id>.")
    )


def _model(argument: str) -> TerminalAction:
    return ModelAction(model_id=argument) if argument else _error("Use model <id>.")


def _blueprint(argument: str) -> TerminalAction:
    return (
        BlueprintAction(blueprint_id=argument)
        if argument
        else _error("Use blueprint <id>.")
    )


def _table(argument: str) -> TerminalAction:
    return (
        TableAction(table_ref=argument)
        if argument
        else _error("Use table silver.<name> or table gold.<name>.")
    )


def _describe(argument: str) -> TerminalAction:
    return (
        DescribeAction(table_ref=argument)
        if argument
        else _error("Use describe silver.<name> or describe gold.<name>.")
    )


def _sql(argument: str) -> TerminalAction:
    limit, statement = _parse_limit(argument)
    statement = _strip_outer_quotes(statement)
    return (
        SqlAction(sql=statement, limit=limit)
        if statement
        else _error("Use sql <read-only statement>.")
    )


COMMANDS = (
    TerminalCommand(
        "help",
        "help",
        "Show Terminal commands.",
        _no_argument(HelpAction()),
        aliases=("?",),
    ),
    TerminalCommand(
        "home",
        "home",
        "Return to the Terminal menu.",
        _no_argument(NavigateAction(href="/")),
        aliases=("menu", "terminal"),
    ),
    TerminalCommand(
        "data",
        "data",
        "Open the Data workspace.",
        _no_argument(NavigateAction(href="/data")),
    ),
    TerminalCommand(
        "eval",
        "eval",
        "Open the Eval workspace.",
        _no_argument(NavigateAction(href="/eval/")),
        aliases=("evals",),
    ),
    TerminalCommand(
        "trade",
        "trade",
        "Show the future Trade workspace.",
        _no_argument(LockedAction()),
    ),
    TerminalCommand(
        "status", "status", "Show the active lake run.", _no_argument(StatusAction())
    ),
    TerminalCommand(
        "clear", "clear", "Clear the command dock.", _no_argument(ClearAction())
    ),
    TerminalCommand(
        "tables",
        "tables",
        "Open the Silver and Gold catalog.",
        _no_argument(CatalogAction(section="tables")),
        "data",
        ("catalog",),
    ),
    TerminalCommand(
        "views",
        "views",
        "Open curated market views.",
        _no_argument(CatalogAction(section="views")),
        "data",
    ),
    TerminalCommand(
        "queries",
        "queries",
        "Open saved SQL queries.",
        _no_argument(CatalogAction(section="queries")),
        "data",
    ),
    TerminalCommand(
        "models",
        "models",
        "Open reusable SQL models.",
        _no_argument(CatalogAction(section="models")),
        "data",
    ),
    TerminalCommand(
        "blueprints",
        "blueprints",
        "Open saved analysis views.",
        _no_argument(CatalogAction(section="blueprints")),
        "data",
        ("analyses",),
    ),
    TerminalCommand(
        "view", "view <view_id>", "Open a Perspective view.", _view, "data"
    ),
    TerminalCommand(
        "query",
        "query <query_id> [--limit N]",
        "Run a saved DataFusion query.",
        _query,
        "data",
    ),
    TerminalCommand("model", "model <id>", "Run a reusable SQL model.", _model, "data"),
    TerminalCommand(
        "blueprint",
        "blueprint <id>",
        "Open a model with its Perspective layout.",
        _blueprint,
        "data",
        ("analysis",),
    ),
    TerminalCommand(
        "table",
        "table <silver|gold>.<name>",
        "Inspect a catalog table.",
        _table,
        "data",
        ("open",),
    ),
    TerminalCommand(
        "describe",
        "describe <silver|gold>.<name>",
        "Inspect a table schema.",
        _describe,
        "data",
        ("schema",),
    ),
    TerminalCommand(
        "sql", "sql [--limit N] <statement>", "Run bounded read-only SQL.", _sql, "data"
    ),
)

COMMAND_BY_NAME = {
    alias: command for command in COMMANDS for alias in (command.name, *command.aliases)
}


def command_catalog() -> list[dict[str, str]]:
    return [command.as_dict() for command in COMMANDS]


def resolve_command(raw: str, *, shell_fallback: bool = False) -> TerminalAction:
    command = raw.strip().removeprefix("/").strip()
    if not command:
        return _error("Enter a command or read-only SQL.")
    if re.match(r"^(select|with|values)\b", command, flags=re.IGNORECASE):
        return SqlAction(sql=command, limit=500)

    verb, _, argument = command.partition(" ")
    definition = COMMAND_BY_NAME.get(verb.lower())
    if definition is None:
        if shell_fallback:
            return ShellAction(command=command)
        return _error(f"Unknown command: {verb}. Try help.")
    return definition.handler(argument.strip())


def _strip_outer_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _parse_limit(value: str, fallback: int = 500) -> tuple[int, str]:
    leading = re.match(r"^--limit\s+(\d+)\s+([\s\S]+)$", value, flags=re.IGNORECASE)
    trailing = re.match(r"^([\s\S]+?)\s+--limit\s+(\d+)$", value, flags=re.IGNORECASE)
    if leading:
        return _bounded_limit(leading.group(1)), leading.group(2).strip()
    if trailing:
        return _bounded_limit(trailing.group(2)), trailing.group(1).strip()
    return fallback, value.strip()


def _bounded_limit(value: str) -> int:
    return max(1, min(MAX_QUERY_LIMIT, int(value)))


def _error(message: str) -> ErrorAction:
    return ErrorAction(message=message)
