"""Compute Bazaar command-line interface."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Annotated, Any

import typer

from .cli_output import render_table_payload, supports_auto_table
from .data_root import LakeSelection, resolve_lake_root
from .prices.schemas import to_jsonable
from .terminal.lifecycle import DEFAULT_EVALUATION_ROOT


class OutputFormat(str, Enum):
    AUTO = "auto"
    TABLE = "table"
    JSON = "json"


class ChartType(str, Enum):
    TABLE = "table"
    LINE = "line"
    BAR = "bar"


@dataclass(frozen=True)
class CLIState:
    lake: LakeSelection
    output_format: OutputFormat


app = typer.Typer(
    help="Query the Compute Bazaar data catalog.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_show_locals=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)
data_app = typer.Typer(help="Inspect or update the local public lake.")
sandbox_app = typer.Typer(help="Maintain StarSling workload costs.")
app.add_typer(data_app, name="data")
app.add_typer(sandbox_app, name="sandbox")


@app.callback()
def configure(
    ctx: typer.Context,
    lake_root: Annotated[
        str | None,
        typer.Option(help="Local or s3:// root containing the manifested lake."),
    ] = None,
    output_format: Annotated[
        OutputFormat,
        typer.Option("--format", help="Output format."),
    ] = OutputFormat.AUTO,
) -> None:
    """Query the Compute Bazaar data catalog."""
    ctx.obj = CLIState(
        lake=resolve_lake_root(lake_root),
        output_format=output_format,
    )


@data_app.command("status")
def data_status(ctx: typer.Context) -> None:
    """Show the selected lake and market run."""
    from .data_sync import inspect_lake

    state = _state(ctx)
    _emit(
        ctx,
        inspect_lake(
            root=state.lake.root,
            kind=state.lake.kind,
            label=state.lake.label,
        ),
        command="data",
        include_source=False,
    )


@data_app.command("sync")
def data_sync(
    ctx: typer.Context,
    url: Annotated[
        str,
        typer.Option(help="Public portable-lake base URL."),
    ] = "https://bazaar.adamsioud.com/lake",
    output_root: Annotated[
        str | None,
        typer.Option(help="Override the local cache directory."),
    ] = None,
) -> None:
    """Download the current sanitized Silver and Gold lake."""
    from .data_sync import sync_public_lake

    _emit(
        ctx,
        sync_public_lake(base_url=url, output_root=output_root),
        command="data",
        include_source=False,
    )


@app.command()
def manifest(ctx: typer.Context) -> None:
    """Show the latest public-safe Gold manifest."""
    _emit(ctx, _service(ctx).manifest(), command="manifest")


@app.command()
def catalog(ctx: typer.Context) -> None:
    """List saved DataFusion queries."""
    _emit(ctx, _service(ctx).catalog(), command="catalog")


@app.command()
def tables(ctx: typer.Context) -> None:
    """List Silver and Gold DataFusion tables."""
    _emit(ctx, _catalog(ctx).tables(), command="tables")


@app.command()
def describe(ctx: typer.Context, table: Annotated[str, typer.Argument()]) -> None:
    """Describe one DataFusion table."""
    _emit(ctx, _catalog(ctx).describe(table), command="describe")


@app.command("query")
def saved_query(
    ctx: typer.Context,
    query_id: Annotated[str, typer.Argument()],
    limit: Annotated[
        int | None,
        typer.Option(help="Override the saved query row limit."),
    ] = None,
    terminal: Annotated[
        bool,
        typer.Option("--terminal", help="Open this result in the Terminal."),
    ] = False,
    port: Annotated[int, typer.Option(min=1, max=65535)] = 8767,
) -> None:
    """Run one saved DataFusion query."""
    from .prices.query_catalog import get_catalog_query

    try:
        query = get_catalog_query(query_id)
    except KeyError as exc:
        raise typer.BadParameter(str(exc).strip("'")) from exc
    selected_limit = _limit(limit if limit is not None else query.default_limit)
    if terminal:
        _launch_native_terminal(
            ctx,
            port=port,
            initial_query=query_id,
            initial_limit=selected_limit,
            evaluation_root=DEFAULT_EVALUATION_ROOT,
        )
        return
    _emit(
        ctx,
        _service(ctx).saved_query(query_id=query_id, limit=selected_limit),
        command="query",
    )


@app.command()
def sql(
    ctx: typer.Context,
    statement: Annotated[str | None, typer.Argument()] = None,
    sql_file: Annotated[
        Path | None,
        typer.Option("--file", help="Read SQL from a file."),
    ] = None,
    limit: Annotated[int, typer.Option()] = 100,
    terminal: Annotated[
        bool,
        typer.Option("--terminal", help="Open this result in the Terminal."),
    ] = False,
    chart: Annotated[
        ChartType | None,
        typer.Option(help="Initial UI view: table, line, or bar."),
    ] = None,
    x: Annotated[
        str | None,
        typer.Option("--x", help="Chart x-axis column."),
    ] = None,
    series: Annotated[
        str | None,
        typer.Option(help="Optional chart series column."),
    ] = None,
    y: Annotated[
        str | None,
        typer.Option("--y", help="Chart value column."),
    ] = None,
    port: Annotated[int, typer.Option(min=1, max=65535)] = 8767,
) -> None:
    """Run bounded read-only SQL over the local catalog."""
    selected_sql = _read_sql(statement=statement, sql_file=sql_file)
    selected_limit = _limit(limit)
    perspective = _perspective_config(chart=chart, x=x, series=series, y=y)
    if perspective and not terminal:
        raise typer.BadParameter("--chart requires --terminal")
    if terminal:
        _launch_native_terminal(
            ctx,
            port=port,
            initial_sql=selected_sql,
            initial_limit=selected_limit,
            initial_perspective=perspective,
            evaluation_root=DEFAULT_EVALUATION_ROOT,
        )
        return
    _emit(
        ctx,
        _catalog(ctx).query(
            selected_sql,
            limit=selected_limit,
        ),
        command="sql",
    )


@app.command("price-index")
def price_index(
    ctx: typer.Context,
    family: Annotated[str | None, typer.Option()] = None,
    history: Annotated[
        bool,
        typer.Option(help="Read retained hourly index snapshots."),
    ] = False,
    limit: Annotated[
        int,
        typer.Option(help="Maximum rows, or market runs when using --history."),
    ] = 20,
) -> None:
    """Read GPU Price Index values."""
    _emit(
        ctx,
        _service(ctx).gpu_price_index(
            family=family,
            history=history,
            limit=_limit(limit),
        ),
        command="price-index",
    )


@app.command()
def availability(
    ctx: typer.Context,
    gpu_model: Annotated[
        str | None,
        typer.Option(help="GPU family or exact model."),
    ] = None,
    measurement_kind: Annotated[str | None, typer.Option()] = None,
    history: Annotated[bool, typer.Option()] = False,
    limit: Annotated[int, typer.Option()] = 100,
) -> None:
    """Read GPU Availability observations."""
    _emit(
        ctx,
        _service(ctx).gpu_availability(
            gpu_model=gpu_model,
            measurement_kind=measurement_kind,
            history=history,
            limit=_limit(limit),
        ),
        command="availability",
    )


@app.command()
def listings(
    ctx: typer.Context,
    gpu_model: Annotated[
        str | None,
        typer.Option(help="GPU family or exact model."),
    ] = None,
    provider: Annotated[str | None, typer.Option()] = None,
    limit: Annotated[int, typer.Option()] = 100,
) -> None:
    """Read normalized Gold listings."""
    _emit(
        ctx,
        _service(ctx).listings(
            gpu_model=gpu_model,
            provider=provider,
            limit=_limit(limit),
        ),
        command="listings",
    )


@app.command()
def providers(
    ctx: typer.Context,
    gpu_model: Annotated[
        str | None,
        typer.Option(help="GPU family or exact model."),
    ] = None,
    limit: Annotated[int, typer.Option()] = 100,
) -> None:
    """Compare provider prices."""
    _emit(
        ctx,
        _service(ctx).providers(gpu_model=gpu_model, limit=_limit(limit)),
        command="providers",
    )


@app.command()
def prime(
    ctx: typer.Context,
    family: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Read the Prime offer market."""
    _emit(ctx, _service(ctx).prime_offers(family=family), command="prime")


@app.command("api")
def serve_api(
    ctx: typer.Context,
    host: Annotated[str, typer.Option()] = "127.0.0.1",
    port: Annotated[int, typer.Option()] = 8766,
    enable_scratch_sql: Annotated[
        bool,
        typer.Option(help="Expose authenticated read-only SQL."),
    ] = False,
) -> None:
    """Serve the typed read-only API."""
    state = _state(ctx)
    _require_lake(state.lake)
    try:
        import uvicorn

        from .api import create_app
    except ImportError as exc:
        raise typer.BadParameter("The API requires: uv sync --extra api") from exc

    uvicorn.run(
        create_app(
            lake_root=state.lake.root,
            enable_scratch_sql=enable_scratch_sql,
        ),
        host=host,
        port=port,
    )


@app.command("terminal")
def serve_terminal(
    ctx: typer.Context,
    port: Annotated[int, typer.Option(min=1, max=65535)] = 8767,
    view: Annotated[
        str | None,
        typer.Option(help="Open a named view."),
    ] = None,
    evaluation_root: Annotated[
        Path,
        typer.Option(help="Local normalized evaluation reports."),
    ] = DEFAULT_EVALUATION_ROOT,
    open_browser: Annotated[
        bool,
        typer.Option(
            "--open/--no-open",
            help="Open a browser when using --foreground.",
        ),
    ] = False,
    foreground: Annotated[
        bool,
        typer.Option("--foreground", help="Keep the server attached and show logs."),
    ] = False,
    stop: Annotated[
        bool,
        typer.Option("--stop", help="Stop the Terminal."),
    ] = False,
    initial_query: Annotated[
        str | None,
        typer.Option("--initial-query", hidden=True),
    ] = None,
    initial_sql: Annotated[
        str | None,
        typer.Option("--initial-sql", hidden=True),
    ] = None,
    initial_limit: Annotated[
        int,
        typer.Option("--initial-limit", hidden=True),
    ] = 500,
    initial_perspective_json: Annotated[
        str | None,
        typer.Option("--initial-perspective", hidden=True),
    ] = None,
) -> None:
    """Open the Compute Bazaar Terminal."""
    if stop:
        _stop_terminal()
        return
    if view:
        from .terminal.views import get_terminal_view

        try:
            get_terminal_view(view)
        except KeyError as exc:
            raise typer.BadParameter(str(exc).strip("'")) from exc
    initial_perspective = _decode_perspective(initial_perspective_json)
    if foreground:
        _run_terminal(
            ctx,
            port=port,
            open_browser=open_browser,
            initial_view=view,
            initial_query=initial_query,
            initial_sql=initial_sql,
            initial_limit=_limit(initial_limit),
            initial_perspective=initial_perspective,
            evaluation_root=evaluation_root,
        )
        return
    _launch_native_terminal(
        ctx,
        port=port,
        initial_view=view,
        initial_query=initial_query,
        initial_sql=initial_sql,
        initial_limit=_limit(initial_limit),
        initial_perspective=initial_perspective,
        evaluation_root=evaluation_root,
    )


def _launch_native_terminal(
    ctx: typer.Context,
    *,
    port: int,
    initial_view: str | None = None,
    initial_query: str | None = None,
    initial_sql: str | None = None,
    initial_limit: int = 500,
    initial_perspective: dict[str, Any] | None = None,
    evaluation_root: Path,
) -> None:
    from .terminal.lifecycle import TerminalLifecycleError, launch_terminal

    state = _state(ctx)
    _require_lake(state.lake)
    try:
        message = launch_terminal(
            lake_root=state.lake.root,
            port=port,
            initial_view=initial_view,
            initial_query=initial_query,
            initial_sql=initial_sql,
            initial_limit=initial_limit,
            initial_perspective=initial_perspective,
            evaluation_root=evaluation_root,
        )
    except TerminalLifecycleError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(message)


def _stop_terminal() -> None:
    from .terminal.lifecycle import TerminalLifecycleError, stop_terminal

    try:
        message = stop_terminal()
    except TerminalLifecycleError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(message)


def _run_terminal(
    ctx: typer.Context,
    *,
    port: int,
    open_browser: bool,
    initial_view: str | None = None,
    initial_query: str | None = None,
    initial_sql: str | None = None,
    initial_limit: int = 500,
    initial_perspective: dict[str, Any] | None = None,
    evaluation_root: Path = DEFAULT_EVALUATION_ROOT,
) -> None:
    from .terminal.lifecycle import TerminalLifecycleError, run_terminal

    state = _state(ctx)
    _require_lake(state.lake)
    try:
        run_terminal(
            lake_root=state.lake.root,
            port=port,
            open_browser=open_browser,
            initial_view=initial_view,
            initial_query=initial_query,
            initial_sql=initial_sql,
            initial_limit=initial_limit,
            initial_perspective=initial_perspective,
            evaluation_root=evaluation_root,
            announce=typer.echo,
        )
    except TerminalLifecycleError as exc:
        raise typer.BadParameter(str(exc)) from exc


def _decode_perspective(value: str | None) -> dict[str, Any] | None:
    if value is None:
        return None
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise typer.BadParameter("Invalid initial Perspective configuration") from exc
    if not isinstance(payload, dict):
        raise typer.BadParameter("Initial Perspective configuration must be an object")
    return payload


def _perspective_config(
    *,
    chart: ChartType | None,
    x: str | None,
    series: str | None,
    y: str | None,
) -> dict[str, Any] | None:
    if chart is None:
        if any((x, series, y)):
            raise typer.BadParameter("--x, --series, and --y require --chart")
        return None
    if chart is ChartType.TABLE:
        if any((x, series, y)):
            raise typer.BadParameter("Table views do not use --x, --series, or --y")
        return {"plugin": "Datagrid", "settings": False}
    if not x or not y:
        raise typer.BadParameter("Line and bar charts require --x and --y")
    config: dict[str, Any] = {
        "plugin": "Y Line" if chart is ChartType.LINE else "Y Bar",
        "group_by": [x],
        "columns": [y],
        "settings": False,
    }
    if series:
        config["split_by"] = [series]
    return config


@sandbox_app.command("build")
def sandbox_build(
    ctx: typer.Context,
    output_root: Annotated[str, typer.Option()] = "data/sandbox-cost",
    dashboard_output_root: Annotated[str | None, typer.Option()] = None,
    workload_benchmark_manifest_ref: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Build the measured-workload data products."""
    from dataclasses import asdict

    from .sandbox_cost.pipeline import build_sandbox_cost

    _emit(
        ctx,
        asdict(
            build_sandbox_cost(
                output_root=output_root,
                dashboard_output_root=dashboard_output_root,
                workload_benchmark_manifest_ref=workload_benchmark_manifest_ref,
            )
        ),
        command="sandbox",
        include_source=False,
    )


@sandbox_app.command("validate")
def sandbox_validate(ctx: typer.Context) -> None:
    """Validate the canonical StarSling evidence."""
    from .sandbox_cost.evidence import validate_evidence

    _emit(
        ctx,
        validate_evidence(),
        command="sandbox",
        include_source=False,
    )


@sandbox_app.command("refresh")
def sandbox_refresh(
    ctx: typer.Context,
    output_root: Annotated[str, typer.Option()] = "data/sandbox-cost",
    source_ref: Annotated[str, typer.Option()] = "main",
    source_repository: Annotated[
        str,
        typer.Option(),
    ] = "starslingdev/hpc-sandbox-benchmarks",
    check: Annotated[bool, typer.Option()] = False,
    update_evidence: Annotated[bool, typer.Option()] = False,
    publish_operational: Annotated[bool, typer.Option()] = False,
) -> None:
    """Fetch StarSling runs and detect new compatible rows."""
    from .sandbox_cost.refresh import refresh_benchmark_sources

    if check and update_evidence:
        raise typer.BadParameter("--check and --update-evidence cannot be combined")
    result = refresh_benchmark_sources(
        output_root=output_root,
        source_ref=source_ref,
        source_repository=source_repository,
        update_evidence=update_evidence,
        publish_operational=publish_operational,
    )
    _emit(ctx, result, command="sandbox", include_source=False)
    if check and result["changed"]:
        raise typer.Exit(1)


@sandbox_app.command("check-public")
def sandbox_check_public(
    ctx: typer.Context,
    url: Annotated[str, typer.Option()],
    max_age_hours: Annotated[float, typer.Option()] = 24 * 8,
) -> None:
    """Validate the public measured-workload payload."""
    from urllib.request import Request, urlopen

    from .sandbox_cost.status import check_public_payload_freshness

    request = Request(
        url,
        headers={"User-Agent": "the-compute-bazaar-freshness-check/1"},
    )
    with urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    result = check_public_payload_freshness(
        payload,
        max_age_hours=max_age_hours,
    )
    _emit(ctx, result, command="sandbox", include_source=False)
    if result["status"] != "ok":
        raise typer.Exit(1)


def _state(ctx: typer.Context) -> CLIState:
    state = ctx.find_root().obj
    if not isinstance(state, CLIState):
        raise RuntimeError("CLI state was not initialized")
    return state


def _service(ctx: typer.Context) -> Any:
    from .market_query_service import MarketQueryService

    state = _state(ctx)
    _require_lake(state.lake)
    return MarketQueryService(lake_root=state.lake.root)


def _catalog(ctx: typer.Context) -> Any:
    from .data_catalog import ComputeBazaarCatalog

    state = _state(ctx)
    _require_lake(state.lake)
    return ComputeBazaarCatalog(lake_root=state.lake.root)


def _require_lake(lake: LakeSelection) -> None:
    if "://" in lake.root:
        return
    manifest = Path(lake.root) / "_manifests" / "gold_market" / "latest.json"
    if manifest.is_file():
        return
    if lake.kind == "public_cache":
        message = "No public lake is synced. Run: compute-bazaar data sync"
    else:
        message = f"No manifested lake exists at {lake.root}"
    raise typer.BadParameter(message)


def _read_sql(*, statement: str | None, sql_file: Path | None) -> str:
    if statement and sql_file:
        raise typer.BadParameter("Provide SQL, --file, or stdin; choose one")
    if sql_file:
        return sql_file.read_text(encoding="utf-8")
    if statement:
        return statement
    if sys.stdin.isatty():
        raise typer.BadParameter(
            "SQL is required through an argument, --file, or stdin"
        )
    return sys.stdin.read()


def _limit(value: int) -> int:
    if not 1 <= value <= 1000:
        raise typer.BadParameter("limit must be between 1 and 1000")
    return value


def _emit(
    ctx: typer.Context,
    payload: Any,
    *,
    command: str,
    include_source: bool = True,
) -> None:
    state = _state(ctx)
    if include_source and isinstance(payload, dict):
        payload = {
            "data_source": state.lake.to_dict(),
            **_compact_cli_run(payload),
        }
    serializable = to_jsonable(payload)
    output_format = state.output_format.value
    if output_format == OutputFormat.AUTO.value:
        output_format = (
            OutputFormat.TABLE.value
            if sys.stdout.isatty() and supports_auto_table(command)
            else OutputFormat.JSON.value
        )
    if output_format == OutputFormat.TABLE.value and isinstance(serializable, dict):
        typer.echo(render_table_payload(serializable, command=command))
    else:
        typer.echo(json.dumps(serializable, indent=2, sort_keys=True))


def _compact_cli_run(payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    run = result.get("run")
    if isinstance(run, dict):
        result["run"] = {
            field: run.get(field)
            for field in ("run_id", "observed_at")
            if run.get(field) is not None
        }
    return result


def main() -> None:
    app(prog_name="compute-bazaar")


if __name__ == "__main__":
    main()
