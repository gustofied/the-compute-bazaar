"""Typed commands shared by the Terminal shell and its workspaces."""

from __future__ import annotations

import json
import re
import shlex
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field

from ..prices.gold_queries import (
    gpu_availability_sql,
    gpu_listings_sql,
    gpu_price_index_sql,
    prime_offer_history_sql,
    provider_comparison_sql,
)
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


class OffersAction(_Action):
    kind: Literal["offers"] = "offers"
    provider: Literal["runpod", "verda"] | None = None
    gpu_model: str | None = None
    offer_id: str | None = None
    include_unavailable: bool = False
    limit: int = 100


class LaunchPlanAction(_Action):
    kind: Literal["launch-plan"] = "launch-plan"
    offer_id: str
    name: str | None = None
    image: str | None = None
    ssh_key_id: str | None = None
    disk_gb: int = 50
    volume_gb: int = 0


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
    | OffersAction
    | LaunchPlanAction
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
    workspace: Literal["terminal", "data", "fleet", "eval", "trade"] = "terminal"
    aliases: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, str]:
        return {
            "command": self.syntax,
            "description": self.description,
            "workspace": self.workspace,
        }


@dataclass(frozen=True)
class ParsedArguments:
    positionals: tuple[str, ...]
    values: dict[str, str]
    flags: frozenset[str]


def _no_argument(action: TerminalAction) -> CommandHandler:
    def handler(_: str) -> TerminalAction:
        return action

    return handler


def _fleet(argument: str) -> TerminalAction:
    return (
        NavigateAction(href="/fleet")
        if not argument
        else _error("Use fleet, or compute-bazaar fleet <operation>.")
    )


def _view(argument: str) -> TerminalAction:
    return ViewAction(view_id=argument) if argument else _error("Use view <view_id>.")


def _query(argument: str) -> TerminalAction:
    parsed = _parse_arguments(
        argument,
        value_options={"limit", "port"},
        flag_options={"terminal"},
    )
    if isinstance(parsed, ErrorAction):
        return parsed
    if len(parsed.positionals) != 1:
        return _error("Use query <query_id> [--limit N].")
    limit = _parsed_limit(parsed, 500)
    return (
        limit
        if isinstance(limit, ErrorAction)
        else QueryAction(query_id=parsed.positionals[0], limit=limit)
    )


def _model(argument: str) -> TerminalAction:
    parsed = _parse_arguments(
        argument,
        value_options={"port"},
        flag_options={"terminal"},
    )
    if isinstance(parsed, ErrorAction):
        return parsed
    positionals = list(parsed.positionals)
    if positionals[:1] == ["list"]:
        return CatalogAction(section="models")
    if positionals[:1] in (["run"], ["show"]):
        positionals.pop(0)
    return (
        ModelAction(model_id=positionals[0])
        if len(positionals) == 1
        else _error("Use model <id> or model run <id>.")
    )


def _blueprint(argument: str) -> TerminalAction:
    parsed = _parse_arguments(argument, value_options={"port"})
    if isinstance(parsed, ErrorAction):
        return parsed
    positionals = list(parsed.positionals)
    if positionals[:1] == ["list"]:
        return CatalogAction(section="blueprints")
    if positionals[:1] in (["open"], ["show"]):
        positionals.pop(0)
    return (
        BlueprintAction(blueprint_id=positionals[0])
        if len(positionals) == 1
        else _error("Use blueprint <id> or blueprint open <id>.")
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


def _cli_sql(argument: str) -> TerminalAction:
    parsed = _parse_arguments(
        argument,
        value_options={
            "limit",
            "port",
            "chart",
            "perspective",
            "x",
            "series",
            "y",
        },
        flag_options={"terminal"},
    )
    if isinstance(parsed, ErrorAction):
        return parsed
    if not parsed.positionals:
        return _error('Use compute-bazaar sql "<read-only statement>".')
    limit = _parsed_limit(parsed, 100)
    if isinstance(limit, ErrorAction):
        return limit
    perspective = _chart_config(parsed)
    if isinstance(perspective, ErrorAction):
        return perspective
    return SqlAction(
        sql=" ".join(parsed.positionals),
        limit=limit,
        perspective=perspective,
    )


def _price_index(argument: str) -> TerminalAction:
    parsed = _parse_arguments(
        argument,
        value_options={"family", "limit"},
        flag_options={"history"},
    )
    if isinstance(parsed, ErrorAction):
        return parsed
    if parsed.positionals:
        return _error("Use price-index [--family GPU] [--history] [--limit N].")
    history = "history" in parsed.flags
    limit = _parsed_limit(parsed, 20)
    if isinstance(limit, ErrorAction):
        return limit
    return SqlAction(
        sql=gpu_price_index_sql(
            table_name=(
                "gold.fact_gpu_price_index_history"
                if history
                else "gold.fact_gpu_price_index"
            ),
            family=parsed.values.get("family"),
            history=history,
        ),
        limit=limit,
        perspective=(
            {
                "plugin": "Y Line",
                "group_by": ["gold_observed_at"],
                "split_by": ["benchmark_family_id"],
                "columns": ["benchmark_usd_gpu_hr"],
                "settings": False,
            }
            if history
            else {
                "plugin": "Y Bar",
                "group_by": ["benchmark_family_id"],
                "columns": ["benchmark_usd_gpu_hr"],
                "settings": False,
            }
        ),
    )


def _availability(argument: str) -> TerminalAction:
    parsed = _parse_arguments(
        argument,
        value_options={"gpu-model", "measurement-kind", "limit"},
        flag_options={"history"},
    )
    if isinstance(parsed, ErrorAction):
        return parsed
    if parsed.positionals:
        return _error(
            "Use availability [--gpu-model GPU] [--measurement-kind KIND] "
            "[--history] [--limit N]."
        )
    history = "history" in parsed.flags
    limit = _parsed_limit(parsed, 100)
    if isinstance(limit, ErrorAction):
        return limit
    return SqlAction(
        sql=gpu_availability_sql(
            table_name=(
                "gold.fact_gpu_availability_history"
                if history
                else "gold.fact_gpu_availability"
            ),
            gpu_model=parsed.values.get("gpu-model"),
            measurement_kind=parsed.values.get("measurement-kind"),
        ),
        limit=limit,
        perspective=_datagrid(),
    )


def _listings(argument: str) -> TerminalAction:
    parsed = _parse_arguments(
        argument,
        value_options={"gpu-model", "provider", "limit"},
    )
    if isinstance(parsed, ErrorAction):
        return parsed
    if parsed.positionals:
        return _error("Use listings [--gpu-model GPU] [--provider NAME] [--limit N].")
    limit = _parsed_limit(parsed, 100)
    if isinstance(limit, ErrorAction):
        return limit
    return SqlAction(
        sql=gpu_listings_sql(
            table_name="gold.fact_gpu_listings",
            gpu_model=parsed.values.get("gpu-model"),
            provider=parsed.values.get("provider"),
        ),
        limit=limit,
        perspective=_datagrid(),
    )


def _providers(argument: str) -> TerminalAction:
    parsed = _parse_arguments(argument, value_options={"gpu-model", "limit"})
    if isinstance(parsed, ErrorAction):
        return parsed
    if parsed.positionals:
        return _error("Use providers [--gpu-model GPU] [--limit N].")
    limit = _parsed_limit(parsed, 100)
    if isinstance(limit, ErrorAction):
        return limit
    return SqlAction(
        sql=provider_comparison_sql(
            table_name="gold.fact_gpu_listings",
            gpu_model=parsed.values.get("gpu-model"),
        ),
        limit=limit,
        perspective=_datagrid(),
    )


def _offers(argument: str) -> TerminalAction:
    parsed = _parse_arguments(
        argument,
        value_options={"provider", "gpu-model", "limit"},
        flag_options={"include-unavailable"},
    )
    if isinstance(parsed, ErrorAction):
        return parsed
    positionals = list(parsed.positionals)
    if positionals[:1] == ["list"]:
        positionals.pop(0)
    offer_id = None
    if positionals[:1] == ["inspect"]:
        positionals.pop(0)
        if len(positionals) != 1:
            return _error("Use offers inspect OFFER_ID.")
        offer_id = positionals.pop(0)
    if positionals:
        return _error(
            "Use offers list [--provider NAME] [--gpu-model GPU] [--limit N]."
        )
    provider = parsed.values.get("provider")
    if provider and provider not in {"runpod", "verda"}:
        return _error("--provider must be runpod or verda.")
    limit = _parsed_limit(parsed, 100)
    if isinstance(limit, ErrorAction):
        return limit
    return OffersAction(
        provider=provider,
        gpu_model=parsed.values.get("gpu-model"),
        offer_id=offer_id,
        include_unavailable="include-unavailable" in parsed.flags,
        limit=limit,
    )


def _launch(argument: str) -> TerminalAction:
    parsed = _parse_arguments(
        argument,
        value_options={
            "name",
            "image",
            "ssh-key-id",
            "disk-gb",
            "volume-gb",
        },
    )
    if isinstance(parsed, ErrorAction):
        return parsed
    positionals = list(parsed.positionals)
    if positionals[:1] == ["plan"]:
        positionals.pop(0)
    if len(positionals) != 1:
        return _error("Use launch plan OFFER_ID [--name NAME] [--image IMAGE].")
    offer_id = positionals[0]
    if ":" not in offer_id:
        return _error(
            "Use the complete offer ID, including its provider, such as runpod:abc123."
        )
    try:
        disk_gb = int(parsed.values.get("disk-gb", "50"))
        volume_gb = int(parsed.values.get("volume-gb", "0"))
    except ValueError:
        return _error("--disk-gb and --volume-gb must be integers.")
    if disk_gb < 1 or volume_gb < 0:
        return _error("--disk-gb must be positive and --volume-gb cannot be negative.")
    return LaunchPlanAction(
        offer_id=offer_id,
        name=parsed.values.get("name"),
        image=parsed.values.get("image"),
        ssh_key_id=parsed.values.get("ssh-key-id"),
        disk_gb=disk_gb,
        volume_gb=volume_gb,
    )


def _prime(argument: str) -> TerminalAction:
    parsed = _parse_arguments(argument, value_options={"family", "limit"})
    if isinstance(parsed, ErrorAction):
        return parsed
    if parsed.positionals:
        return _error("Use prime [--family GPU] [--limit N].")
    limit = _parsed_limit(parsed, 672)
    if isinstance(limit, ErrorAction):
        return limit
    return SqlAction(
        sql=prime_offer_history_sql(
            table_name="gold.fact_prime_frontier_offer_reference_history",
            family=parsed.values.get("family"),
        ),
        limit=limit,
        perspective={
            "plugin": "Y Line",
            "group_by": ["gold_observed_at"],
            "split_by": ["gpu_family_id"],
            "columns": ["reference_usd_gpu_hr"],
            "settings": False,
        },
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
        "fleet",
        "fleet",
        "Open the Fleet workspace.",
        _fleet,
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
        "sql", "sql [--limit N] <statement>", "Run read-only SQL.", _sql, "data"
    ),
    TerminalCommand(
        "price-index",
        "price-index [--family GPU] [--history] [--limit N]",
        "Read GPU Price Index values.",
        _price_index,
        "data",
    ),
    TerminalCommand(
        "availability",
        "availability [--gpu-model GPU] [--history] [--limit N]",
        "Read GPU Availability observations.",
        _availability,
        "data",
    ),
    TerminalCommand(
        "listings",
        "listings [--gpu-model GPU] [--provider NAME] [--limit N]",
        "Read normalized GPU listings.",
        _listings,
        "data",
    ),
    TerminalCommand(
        "offers",
        "offers list [--provider NAME] [--gpu-model GPU] [--limit N]",
        "Fetch current RunPod and Verda offers.",
        _offers,
        "data",
    ),
    TerminalCommand(
        "launch",
        "launch plan OFFER_ID [--name NAME] [--image IMAGE]",
        "Prepare a provider request without creating a machine.",
        _launch,
        "data",
    ),
    TerminalCommand(
        "providers",
        "providers [--gpu-model GPU] [--limit N]",
        "Compare provider prices.",
        _providers,
        "data",
    ),
    TerminalCommand(
        "prime",
        "prime [--family GPU] [--limit N]",
        "Read the Prime offer market.",
        _prime,
        "data",
    ),
)

COMMAND_BY_NAME = {
    alias: command for command in COMMANDS for alias in (command.name, *command.aliases)
}


def command_catalog() -> list[dict[str, str]]:
    return [command.as_dict() for command in COMMANDS]


def resolve_command(raw: str, *, shell_fallback: bool = False) -> TerminalAction:
    original = re.sub(r"\\[ \t]*\r?\n[ \t]*", " ", raw)
    original = original.strip().removeprefix("/").strip()
    command, cli_prefixed = _strip_cli_prefix(original)
    if not command:
        return (
            HelpAction()
            if cli_prefixed
            else _error("Enter a command or read-only SQL.")
        )
    if cli_prefixed:
        boundary_action = _resolve_cli_boundary(
            command,
            original=original,
            shell_fallback=shell_fallback,
        )
        if boundary_action is not None:
            return boundary_action
    if re.match(r"^(select|with|values)\b", command, flags=re.IGNORECASE):
        return SqlAction(sql=command, limit=500)

    verb, _, argument = command.partition(" ")
    if verb.lower() == "fleet" and argument.strip() and shell_fallback:
        return ShellAction(command=f"compute-bazaar fleet {argument.strip()}")
    definition = COMMAND_BY_NAME.get(verb.lower())
    if definition is None:
        if cli_prefixed:
            return _error(f"Unknown Compute Bazaar command: {verb}. Try help.")
        if shell_fallback:
            return ShellAction(command=command)
        return _error(f"Unknown command: {verb}. Try help.")
    return definition.handler(argument.strip())


def _strip_cli_prefix(command: str) -> tuple[str, bool]:
    for prefix in ("uv run compute-bazaar", "compute-bazaar"):
        if command.lower() == prefix:
            return "", True
        if command.lower().startswith(prefix + " "):
            return command[len(prefix) :].strip(), True
    return command, False


def _resolve_cli_boundary(
    command: str,
    *,
    original: str,
    shell_fallback: bool,
) -> TerminalAction | None:
    verb, _, argument = command.partition(" ")
    verb = verb.lower()
    argument = argument.strip()
    if verb in {"-h", "--help"}:
        return HelpAction()
    if verb == "sql":
        return _cli_sql(argument)
    if verb == "data":
        subcommand = argument.partition(" ")[0].lower()
        if not subcommand:
            return NavigateAction(href="/data")
        if subcommand == "status":
            return StatusAction()
        if subcommand == "sync":
            return (
                ShellAction(command=original)
                if shell_fallback
                else _error("Data sync requires the native Terminal shell.")
            )
        return _error(f"Unknown data command: {subcommand}.")
    if verb == "fleet":
        if not argument:
            return NavigateAction(href="/fleet")
        return (
            ShellAction(command=original)
            if shell_fallback
            else _error("Fleet operations require the native Terminal shell.")
        )
    if verb == "manifest":
        return StatusAction()
    if verb == "catalog":
        return CatalogAction(section="queries")
    if verb == "terminal":
        return NavigateAction(href="/")
    if verb in {"api", "sandbox"}:
        return (
            ShellAction(command=original)
            if shell_fallback
            else _error(f"{verb} requires the native Terminal shell.")
        )
    if verb in {"model", "blueprint"} and argument.partition(" ")[0].lower() in {
        "save",
        "delete",
    }:
        return (
            ShellAction(command=original)
            if shell_fallback
            else _error(f"{verb} writes require the native Terminal shell.")
        )
    return None


def _strip_outer_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _parse_arguments(
    value: str,
    *,
    value_options: set[str] | None = None,
    flag_options: set[str] | None = None,
) -> ParsedArguments | ErrorAction:
    try:
        tokens = shlex.split(value)
    except ValueError as exc:
        return _error(str(exc))
    expected_values = value_options or set()
    expected_flags = flag_options or set()
    positionals: list[str] = []
    values: dict[str, str] = {}
    flags: set[str] = set()
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if not token.startswith("--"):
            positionals.append(token)
            index += 1
            continue
        option, separator, inline_value = token[2:].partition("=")
        if option in expected_flags:
            if separator:
                return _error(f"--{option} does not take a value.")
            flags.add(option)
            index += 1
            continue
        if option not in expected_values:
            return _error(f"Unknown option: --{option}.")
        if separator:
            values[option] = inline_value
            index += 1
            continue
        if index + 1 >= len(tokens) or tokens[index + 1].startswith("--"):
            return _error(f"--{option} requires a value.")
        values[option] = tokens[index + 1]
        index += 2
    return ParsedArguments(tuple(positionals), values, frozenset(flags))


def _parsed_limit(
    parsed: ParsedArguments,
    fallback: int,
) -> int | ErrorAction:
    value = parsed.values.get("limit")
    if value is None:
        return fallback
    try:
        return _bounded_limit(value)
    except ValueError:
        return _error("--limit must be an integer.")


def _chart_config(parsed: ParsedArguments) -> dict[str, Any] | None | ErrorAction:
    perspective = parsed.values.get("perspective")
    if perspective is not None:
        if any(option in parsed.values for option in ("chart", "x", "series", "y")):
            return _error(
                "--perspective cannot be combined with --chart, --x, --series, or --y."
            )
        try:
            config = json.loads(perspective)
        except json.JSONDecodeError:
            return _error("--perspective must be a JSON object.")
        if not isinstance(config, dict):
            return _error("--perspective must be a JSON object.")
        return config
    chart = parsed.values.get("chart")
    if chart is None:
        return None
    chart = chart.lower()
    if chart == "table":
        return _datagrid()
    if chart not in {"line", "bar", "area"}:
        return _error("--chart must be table, line, bar, or area.")
    x = parsed.values.get("x")
    y = parsed.values.get("y")
    if not x or not y:
        return _error("Line, bar, and area charts require --x and --y.")
    plugins = {"line": "Y Line", "bar": "Y Bar", "area": "Y Area"}
    config: dict[str, Any] = {
        "plugin": plugins[chart],
        "group_by": [x],
        "columns": [y],
        "settings": False,
    }
    if series := parsed.values.get("series"):
        config["split_by"] = [series]
    return config


def _datagrid() -> dict[str, Any]:
    return {"plugin": "Datagrid", "settings": False}


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
