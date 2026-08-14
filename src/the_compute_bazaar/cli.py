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
market_app = typer.Typer(help="Read market sources into a local lake.")
sandbox_app = typer.Typer(help="Maintain StarSling workload costs.")
model_app = typer.Typer(help="Save and run reusable DataFusion SQL models.")
blueprint_app = typer.Typer(help="Save and open Perspective views of SQL models.")
offers_app = typer.Typer(help="Read offers directly from compute providers.")
launch_app = typer.Typer(help="Plan provider-native compute launches.")
fleet_app = typer.Typer(help="Attach, inspect, and operate NVIDIA compute.")
workload_app = typer.Typer(help="Run and inspect commands on Fleet hosts.")
app.add_typer(data_app, name="data")
app.add_typer(market_app, name="market")
app.add_typer(sandbox_app, name="sandbox")
app.add_typer(model_app, name="model")
app.add_typer(blueprint_app, name="blueprint")
app.add_typer(offers_app, name="offers")
app.add_typer(launch_app, name="launch")
app.add_typer(fleet_app, name="fleet")
fleet_app.add_typer(workload_app, name="workload")


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


@market_app.command("ingest")
def market_ingest(
    ctx: typer.Context,
    source: Annotated[str, typer.Argument()],
    output_root: Annotated[
        str | None,
        typer.Option(help="Local market-lake directory."),
    ] = None,
) -> None:
    """Read one source and publish a queryable local generation."""
    import os

    from .market import (
        MarketLake,
        MarketPipeline,
        default_market_lake_root,
        default_registry,
        publish_generation,
    )

    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass
    root = output_root or default_market_lake_root()
    lake = MarketLake(root)
    result = MarketPipeline(lake).run(
        default_registry.build(source, environment=os.environ)
    )
    if result.run.status != "complete":
        raise typer.BadParameter(result.run.error or f"{source} read failed")
    _emit(
        ctx,
        publish_generation(lake, result),
        command="market",
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
    try:
        result = _catalog(ctx).query(selected_sql, limit=selected_limit)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from None
    _emit(ctx, result, command="sql")


@model_app.command("list")
def model_list(ctx: typer.Context) -> None:
    """List repo-backed analysis models."""
    from .analysis_store import model_payload

    rows = []
    for model in _analysis_store().list_models():
        payload = model_payload(model)
        payload.pop("sql", None)
        rows.append(payload)
    _emit(
        ctx,
        {"analysis_root": str(_analysis_store().root), "models": rows},
        command="model",
        include_source=False,
    )


@model_app.command("show")
def model_show(ctx: typer.Context, model_id: Annotated[str, typer.Argument()]) -> None:
    """Show one analysis model and its SQL."""
    from .analysis_store import model_payload

    try:
        model = _analysis_store().load_model(model_id)
    except (FileNotFoundError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    _emit(
        ctx,
        model_payload(model),
        command="model",
        include_source=False,
    )


@model_app.command("save")
def model_save(
    ctx: typer.Context,
    model_id: Annotated[str, typer.Argument()],
    sql_file: Annotated[
        Path | None,
        typer.Option("--file", help="Read model SQL from a file; otherwise stdin."),
    ] = None,
    title: Annotated[str | None, typer.Option()] = None,
    description: Annotated[str, typer.Option()] = "",
    limit: Annotated[int, typer.Option()] = 500,
) -> None:
    """Save a read-only SQL model locally."""
    from .analysis_store import model_payload

    statement = _read_sql(statement=None, sql_file=sql_file)
    try:
        _catalog(ctx).query_arrow(statement, limit=1)
        model = _analysis_store().save_model(
            model_id=model_id,
            title=title or model_id.replace("-", " ").title(),
            description=description,
            sql=statement,
            default_limit=_limit(limit),
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    _emit(
        ctx,
        model_payload(model),
        command="model",
        include_source=False,
    )


@model_app.command("run")
def model_run(
    ctx: typer.Context,
    model_id: Annotated[str, typer.Argument()],
    limit: Annotated[int | None, typer.Option()] = None,
    blueprint: Annotated[
        str | None,
        typer.Option(help="Perspective blueprint to use with --terminal."),
    ] = None,
    terminal: Annotated[bool, typer.Option("--terminal")] = False,
    port: Annotated[int, typer.Option(min=1, max=65535)] = 8767,
) -> None:
    """Run a saved model headlessly or open it in the Terminal."""
    store = _analysis_store()
    try:
        model = store.load_model(model_id)
        layout = store.load_blueprint(blueprint) if blueprint else None
    except (FileNotFoundError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    if layout and layout.model_id != model.model_id:
        raise typer.BadParameter(
            f"Blueprint {layout.blueprint_id} uses model {layout.model_id}"
        )
    selected_limit = _limit(limit or model.default_limit)
    if terminal:
        _launch_native_terminal(
            ctx,
            port=port,
            initial_sql=model.sql,
            initial_limit=selected_limit,
            initial_perspective=layout.viewer_config if layout else None,
            evaluation_root=DEFAULT_EVALUATION_ROOT,
        )
        return
    _emit(
        ctx,
        _catalog(ctx).query(model.sql, limit=selected_limit),
        command="sql",
    )


@model_app.command("delete")
def model_delete(model_id: Annotated[str, typer.Argument()]) -> None:
    """Delete a model that has no blueprints."""
    try:
        _analysis_store().delete_model(model_id)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(f"Deleted model {model_id}.")


@blueprint_app.command("list")
def blueprint_list(ctx: typer.Context) -> None:
    """List local and bundled Perspective blueprints."""
    from .analysis_store import blueprint_payload

    _emit(
        ctx,
        {
            "analysis_root": str(_analysis_store().root),
            "blueprints": [
                blueprint_payload(blueprint)
                for blueprint in _analysis_store().list_blueprints()
            ],
        },
        command="blueprint",
        include_source=False,
    )


@blueprint_app.command("show")
def blueprint_show(
    ctx: typer.Context,
    blueprint_id: Annotated[str, typer.Argument()],
) -> None:
    """Show one blueprint and its linked model."""
    from .analysis_store import blueprint_payload

    try:
        blueprint = _analysis_store().load_blueprint(blueprint_id)
    except (FileNotFoundError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    _emit(
        ctx,
        blueprint_payload(blueprint),
        command="blueprint",
        include_source=False,
    )


@blueprint_app.command("save")
def blueprint_save(
    ctx: typer.Context,
    blueprint_id: Annotated[str, typer.Argument()],
    model_id: Annotated[str, typer.Option("--model")],
    config: Annotated[Path, typer.Option("--config", help="Perspective JSON file.")],
    title: Annotated[str | None, typer.Option()] = None,
    description: Annotated[str, typer.Option()] = "",
    markdown: Annotated[
        Path | None,
        typer.Option("--markdown", help="Optional Markdown file."),
    ] = None,
) -> None:
    """Attach a Perspective layout to a saved model."""
    from .analysis_store import blueprint_payload

    try:
        viewer_config = json.loads(config.read_text(encoding="utf-8"))
        if not isinstance(viewer_config, dict):
            raise ValueError("Perspective config must be a JSON object")
        blueprint = _analysis_store().save_blueprint(
            blueprint_id=blueprint_id,
            model_id=model_id,
            title=title or blueprint_id.replace("-", " ").title(),
            description=description,
            markdown=(markdown.read_text(encoding="utf-8") if markdown else ""),
            viewer="perspective",
            viewer_config=viewer_config,
        )
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    _emit(
        ctx,
        blueprint_payload(blueprint),
        command="blueprint",
        include_source=False,
    )


@blueprint_app.command("open")
def blueprint_open(
    ctx: typer.Context,
    blueprint_id: Annotated[str, typer.Argument()],
    port: Annotated[int, typer.Option(min=1, max=65535)] = 8767,
) -> None:
    """Open a saved model and blueprint in the Terminal."""
    store = _analysis_store()
    try:
        blueprint = store.load_blueprint(blueprint_id)
        model = store.load_model(blueprint.model_id)
    except (FileNotFoundError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    _launch_native_terminal(
        ctx,
        port=port,
        initial_sql=model.sql,
        initial_limit=model.default_limit,
        initial_perspective=blueprint.viewer_config,
        evaluation_root=DEFAULT_EVALUATION_ROOT,
    )


@blueprint_app.command("delete")
def blueprint_delete(blueprint_id: Annotated[str, typer.Argument()]) -> None:
    """Delete one Perspective blueprint."""
    try:
        _analysis_store().delete_blueprint(blueprint_id)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(f"Deleted blueprint {blueprint_id}.")


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


@offers_app.command("list")
def offers_list(
    ctx: typer.Context,
    provider: Annotated[
        list[str] | None,
        typer.Option("--provider", help="Direct provider: runpod or verda."),
    ] = None,
    gpu_model: Annotated[
        str | None,
        typer.Option(help="GPU family or exact model."),
    ] = None,
    include_unavailable: Annotated[
        bool,
        typer.Option(help="Include provider products with no live stock."),
    ] = False,
    limit: Annotated[int, typer.Option()] = 100,
) -> None:
    """Read current provider offers and record the observations locally."""
    try:
        result = _offers().list_offers(
            providers=provider,
            gpu_model=gpu_model,
            include_unavailable=include_unavailable,
            limit=_limit(limit),
        )
    except RuntimeError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if not result.observations:
        failures = [
            status.message or status.status
            for status in result.providers
            if status.status != "ok"
        ]
        if failures:
            raise typer.BadParameter("; ".join(failures))
    _emit(
        ctx,
        result.payload(),
        command="offers",
        include_source=False,
    )


@offers_app.command("inspect")
def offers_inspect(
    ctx: typer.Context,
    offer_id: Annotated[str, typer.Argument()],
) -> None:
    """Re-fetch and inspect one provider-native offer selection."""
    from .offers import display_row

    try:
        offer = _offers().inspect(offer_id)
    except RuntimeError as exc:
        raise typer.BadParameter(str(exc)) from exc
    _emit(
        ctx,
        {
            "contract": "compute-bazaar.offer-observation",
            "observed_at": offer.observed_at,
            "rows": [display_row(offer)],
            "selection": offer.native_selection,
        },
        command="offers",
        include_source=False,
    )


@launch_app.command("plan")
def launch_plan(
    ctx: typer.Context,
    offer_id: Annotated[str, typer.Argument()],
    name: Annotated[str | None, typer.Option(help="Machine name or hostname.")] = None,
    image: Annotated[
        str | None, typer.Option(help="Provider image identifier.")
    ] = None,
    ssh_key_id: Annotated[
        list[str] | None,
        typer.Option("--ssh-key-id", help="Provider SSH key identifier."),
    ] = None,
    disk_gb: Annotated[int, typer.Option(help="Operating-system disk size.")] = 50,
    volume_gb: Annotated[int, typer.Option(help="RunPod workspace volume size.")] = 0,
) -> None:
    """Revalidate an offer and prepare a request without provisioning it."""
    from .offers import OfferServiceError
    from .provisioning import LaunchPlanner

    try:
        plan = LaunchPlanner.from_environment().plan(
            offer_id,
            name=name,
            image=image,
            ssh_key_ids=tuple(ssh_key_id or ()),
            disk_gb=disk_gb,
            volume_gb=volume_gb,
        )
    except (OfferServiceError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    _emit(ctx, plan.payload(), command="launch", include_source=False)


@launch_app.command("run")
def launch_run(
    ctx: typer.Context,
    offer_id: Annotated[str, typer.Argument()],
    name: Annotated[str, typer.Option(help="Machine name.")],
    image: Annotated[str, typer.Option(help="RunPod container image.")],
    max_hourly_usd: Annotated[
        float,
        typer.Option(help="Refuse the launch above this instance-hour price."),
    ],
    runtime_minutes: Annotated[
        int,
        typer.Option(help="Provider-side termination deadline, from 5 to 120 minutes."),
    ] = 30,
    disk_gb: Annotated[int, typer.Option(help="Container disk size.")] = 50,
    confirm_spend: Annotated[
        bool,
        typer.Option("--confirm-spend", help="Confirm creation of a paid RunPod Pod."),
    ] = False,
) -> None:
    """Revalidate an offer, launch it with a deadline, and register the host."""
    from .offers import OfferServiceError
    from .operations import OperationalLedger
    from .provider_execution import LaunchExecutionError, RunpodExecutor
    from .provisioning import LaunchPlanner

    planner = LaunchPlanner.from_environment()
    ledger = OperationalLedger()
    try:
        plan = planner.plan(
            offer_id,
            name=name,
            image=image,
            disk_gb=disk_gb,
            volume_gb=0,
        )
        receipt = RunpodExecutor(
            api_key=planner.service.runpod_api_key,
            ledger=ledger,
        ).execute(
            plan,
            runtime_minutes=runtime_minutes,
            max_hourly_usd=max_hourly_usd,
            confirm_spend=confirm_spend,
        )
    except (LaunchExecutionError, OfferServiceError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    _emit(ctx, receipt.payload(), command="launch", include_source=False)


@launch_app.command("reconcile")
def launch_reconcile(
    ctx: typer.Context,
    attempt_id: Annotated[str, typer.Argument()],
    confirm_absent: Annotated[
        bool,
        typer.Option(
            "--confirm-absent",
            help="Mark the attempt failed after checking that no matching Pod exists.",
        ),
    ] = False,
) -> None:
    """Resolve an uncertain launch against current RunPod state."""
    from .fleet import FleetRegistry
    from .offers import OfferService
    from .operations import OperationalLedger, ProvisioningStateError
    from .provider_execution import LaunchExecutionError, RunpodExecutor

    registry = FleetRegistry()
    ledger = OperationalLedger(registry=registry)
    try:
        service = OfferService.from_environment()
        receipt = RunpodExecutor(
            api_key=service.runpod_api_key,
            registry=registry,
            ledger=ledger,
        ).reconcile(attempt_id, confirm_absent=confirm_absent)
    except (KeyError, LaunchExecutionError, ProvisioningStateError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    _emit(ctx, receipt.payload(), command="launch", include_source=False)


@fleet_app.command("hosts")
def fleet_hosts(ctx: typer.Context) -> None:
    """List machines known to the private local Fleet registry."""
    from .fleet import FleetService

    machines = FleetService.local().hosts()
    _emit(
        ctx,
        {
            "contract": "compute-bazaar.fleet-hosts",
            "rows": [machine.row() for machine in machines],
        },
        command="fleet",
        include_source=False,
    )


@fleet_app.command("plan")
def fleet_plan(
    ctx: typer.Context,
    observation_id: Annotated[str, typer.Argument()],
    name: Annotated[str, typer.Option(help="Machine name.")],
    ssh_key_id: Annotated[str, typer.Option(help="Sesterce SSH key ID.")],
    os_name: Annotated[str | None, typer.Option("--os", help="Sesterce VM image.")] = None,
) -> None:
    """Recheck one Sesterce observation and show the create request."""
    try:
        plan = _sesterce_launcher(ctx).plan(
            observation_id,
            name=name,
            ssh_key_id=ssh_key_id,
            os_name=os_name,
        )
    except (KeyError, RuntimeError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    _emit(ctx, plan.payload(), command="launch", include_source=False)


@fleet_app.command("launch")
def fleet_launch(
    ctx: typer.Context,
    observation_id: Annotated[str, typer.Argument()],
    name: Annotated[str, typer.Option(help="Machine name.")],
    ssh_key_id: Annotated[str, typer.Option(help="Sesterce SSH key ID.")],
    max_hourly_usd: Annotated[
        float,
        typer.Option(help="Refuse the launch above this total hourly price."),
    ],
    os_name: Annotated[str | None, typer.Option("--os", help="Sesterce VM image.")] = None,
    wait_seconds: Annotated[
        int,
        typer.Option(min=0, help="Wait for an SSH endpoint, in seconds."),
    ] = 180,
    confirm: Annotated[
        bool,
        typer.Option("--confirm", help="Create the paid Sesterce instance."),
    ] = False,
) -> None:
    """Create one Sesterce instance and add it to Fleet."""
    try:
        plan, machine = _sesterce_launcher(ctx).launch(
            observation_id,
            name=name,
            ssh_key_id=ssh_key_id,
            max_hourly_usd=max_hourly_usd,
            confirm=confirm,
            os_name=os_name,
            wait_seconds=wait_seconds,
        )
    except (KeyError, RuntimeError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    _emit(
        ctx,
        {
            "contract": "compute-bazaar.fleet-launch",
            "observed_at": plan.observed_at,
            "rows": [machine.row()],
        },
        command="fleet",
        include_source=False,
    )


@fleet_app.command("attach")
def fleet_attach(
    ctx: typer.Context,
    ssh_target: Annotated[
        str,
        typer.Argument(help="OpenSSH config host or user@host."),
    ],
    name: Annotated[str | None, typer.Option(help="Fleet display name.")] = None,
    expected_gpu_model: Annotated[
        str | None,
        typer.Option("--expect", help="Expected NVIDIA GPU model."),
    ] = None,
    expected_gpu_count: Annotated[
        int | None,
        typer.Option("--count", min=1, help="Expected NVIDIA GPU count."),
    ] = None,
) -> None:
    """Attach an existing NVIDIA machine through native OpenSSH."""
    from .fleet import FleetInspectError, FleetService

    try:
        inspection, health = FleetService.local().attach(
            ssh_target,
            name=name,
            expected_gpu_model=expected_gpu_model,
            expected_gpu_count=expected_gpu_count,
        )
    except (FleetInspectError, KeyError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    _emit(
        ctx,
        {
            "contract": "compute-bazaar.fleet-attachment",
            "observed_at": inspection.observed_at,
            "rows": [
                {
                    **inspection.machine.row(),
                    **inspection.row(),
                    "health": health.health,
                }
            ],
        },
        command="fleet",
        include_source=False,
    )


@fleet_app.command("inspect")
def fleet_inspect(
    ctx: typer.Context,
    host_id: Annotated[str, typer.Argument()],
) -> None:
    """Collect read-only system and GPU facts over SSH."""
    from .fleet import FleetInspectError, FleetService

    try:
        inspection = FleetService.local().inspect(host_id)
    except (FleetInspectError, KeyError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    _emit(
        ctx,
        {
            "contract": "compute-bazaar.fleet-inspection",
            "observed_at": inspection.observed_at,
            "rows": [inspection.row()],
            "inspection": inspection.model_dump(mode="json"),
        },
        command="fleet",
        include_source=False,
    )


@fleet_app.command("refresh")
def fleet_refresh(
    ctx: typer.Context,
    host_id: Annotated[str, typer.Argument()],
) -> None:
    """Refresh the SSH endpoint of a newly provisioned RunPod host."""
    from .fleet import FleetRegistry
    from .offers import OfferService
    from .operations import OperationalLedger
    from .provider_execution import LaunchExecutionError, RunpodExecutor

    registry = FleetRegistry()
    try:
        machine = registry.get(host_id)
        service = OfferService.from_environment()
        refreshed = RunpodExecutor(
            api_key=service.runpod_api_key,
            registry=registry,
            ledger=OperationalLedger(),
        ).resolve_ssh(machine)
    except (KeyError, LaunchExecutionError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    _emit(
        ctx,
        {
            "contract": "compute-bazaar.fleet-refresh",
            "rows": [refreshed.row()],
        },
        command="fleet",
        include_source=False,
    )


@fleet_app.command("doctor")
def fleet_doctor(
    ctx: typer.Context,
    host_id: Annotated[str, typer.Argument()],
) -> None:
    """Evaluate one machine as workload-ready GPU capacity."""
    from .fleet import FleetInspectError, FleetService

    try:
        result = FleetService.local().doctor(host_id)
    except (FleetInspectError, KeyError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    _emit(ctx, result.payload(), command="fleet-doctor", include_source=False)


@fleet_app.command("terminate")
def fleet_terminate(
    ctx: typer.Context,
    host_id: Annotated[str, typer.Argument()],
    confirm: Annotated[
        bool,
        typer.Option("--confirm", help="Confirm permanent provider deletion."),
    ] = False,
) -> None:
    """Delete one provider instance and mark it terminated locally."""
    from .fleet import FleetRegistry
    from .offers import OfferService
    from .operations import OperationalLedger
    from .provider_execution import LaunchExecutionError, RunpodExecutor

    registry = FleetRegistry()
    try:
        machine = registry.get(host_id)
        if machine.source == "sesterce":
            terminated = _sesterce_launcher(ctx).terminate(host_id, confirm=confirm)
            _emit(
                ctx,
                {
                    "contract": "compute-bazaar.fleet-termination",
                    "rows": [terminated.row()],
                },
                command="fleet",
                include_source=False,
            )
            return
        service = OfferService.from_environment()
        terminated = RunpodExecutor(
            api_key=service.runpod_api_key,
            registry=registry,
            ledger=OperationalLedger(),
        ).terminate(machine, confirm=confirm)
    except (KeyError, LaunchExecutionError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    _emit(
        ctx,
        {
            "contract": "compute-bazaar.fleet-termination",
            "rows": [terminated.row()],
        },
        command="fleet",
        include_source=False,
    )


@workload_app.command("run")
def fleet_workload_run(
    ctx: typer.Context,
    host_id: Annotated[str, typer.Argument()],
    command: Annotated[
        list[str],
        typer.Argument(help="Command and arguments. Put them after --."),
    ],
    name: Annotated[str, typer.Option(help="Workload name.")] = "workload",
    working_directory: Annotated[
        str,
        typer.Option("--cwd", help="Remote working directory."),
    ] = "/tmp",
) -> None:
    """Start one durable command over SSH."""
    from .fleet import WorkloadError, WorkloadService

    try:
        workload = WorkloadService.local().start(
            host_id,
            name=name,
            command=command,
            working_directory=working_directory,
        )
    except (KeyError, WorkloadError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    _emit_workload(ctx, workload)


@workload_app.command("list")
def fleet_workload_list(
    ctx: typer.Context,
    host_id: Annotated[
        str | None,
        typer.Option("--host", help="Only workloads for this Fleet host."),
    ] = None,
) -> None:
    """List recorded Fleet workloads."""
    from .fleet import WorkloadService

    workloads = WorkloadService.local().list(host_id)
    _emit(
        ctx,
        {
            "contract": "compute-bazaar.fleet-workloads",
            "rows": [workload.row() for workload in workloads],
        },
        command="workload",
        include_source=False,
    )


@workload_app.command("inspect")
def fleet_workload_inspect(
    ctx: typer.Context,
    workload_id: Annotated[str, typer.Argument()],
) -> None:
    """Refresh and show one workload."""
    from .fleet import WorkloadError, WorkloadService

    try:
        workload = WorkloadService.local().inspect(workload_id)
    except (KeyError, WorkloadError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    _emit_workload(ctx, workload)


@workload_app.command("logs")
def fleet_workload_logs(
    ctx: typer.Context,
    workload_id: Annotated[str, typer.Argument()],
    tail: Annotated[int, typer.Option(help="Maximum lines from each stream.")] = 200,
) -> None:
    """Refresh and print one workload's output."""
    from .fleet import WorkloadError, WorkloadService

    try:
        payload = WorkloadService.local().logs(workload_id, tail=tail)
    except (KeyError, WorkloadError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    _emit(ctx, payload, command="workload-logs", include_source=False)


@workload_app.command("stop")
def fleet_workload_stop(
    ctx: typer.Context,
    workload_id: Annotated[str, typer.Argument()],
    confirm: Annotated[
        bool,
        typer.Option("--confirm", help="Confirm remote process termination."),
    ] = False,
) -> None:
    """Stop one remote workload process group."""
    from .fleet import WorkloadError, WorkloadService

    try:
        workload = WorkloadService.local().stop(workload_id, confirm=confirm)
    except (KeyError, WorkloadError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    _emit_workload(ctx, workload)


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
        raise typer.BadParameter("The API requires: uv sync --extra terminal") from exc

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
    lake: Annotated[
        str | None,
        typer.Argument(help="Use lake2 to open the new market lake."),
    ] = None,
    port: Annotated[int, typer.Option(min=1, max=65535)] = 8767,
    view: Annotated[
        str | None,
        typer.Option(help="Open a named view."),
    ] = None,
    evaluation_root: Annotated[
        Path,
        typer.Option(help="Local evaluation reports and notes."),
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
    if lake:
        if lake != "lake2":
            raise typer.BadParameter("Unknown lake. Use lake2 or omit it.")
        from .market import default_market_lake_root

        state = _state(ctx)
        ctx.find_root().obj = CLIState(
            lake=resolve_lake_root(default_market_lake_root()),
            output_format=state.output_format,
        )
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
    from .data_catalog import open_catalog
    from .operations import OperationalLedger

    state = _state(ctx)
    _require_lake(state.lake)
    return open_catalog(
        lake_root=state.lake.root,
        operations=OperationalLedger(),
    )


def _analysis_store() -> Any:
    from .analysis_store import AnalysisStore

    return AnalysisStore()


def _sesterce_launcher(ctx: typer.Context) -> Any:
    import os

    from .market import SesterceLauncher, SesterceSource, default_market_lake_root

    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass
    state = _state(ctx)
    lake_root = (
        state.lake.root if state.lake.kind == "explicit" else default_market_lake_root()
    )
    return SesterceLauncher(
        lake_root=lake_root,
        source=SesterceSource(os.getenv("SESTERCE_API_KEY", "")),
    )


def _offers() -> Any:
    from .offers import OfferService

    return OfferService.from_environment()


def _require_lake(lake: LakeSelection) -> None:
    if "://" in lake.root:
        return
    manifests = (
        Path(lake.root) / "_manifests" / "market" / "latest.json",
        Path(lake.root) / "_manifests" / "gold_market" / "latest.json",
    )
    if any(manifest.is_file() for manifest in manifests):
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


def _emit_workload(ctx: typer.Context, workload: Any) -> None:
    _emit(
        ctx,
        {
            "contract": "compute-bazaar.fleet-workloads",
            "rows": [workload.row()],
            "workload": workload.model_dump(mode="json"),
        },
        command="workload",
        include_source=False,
    )


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
            for field in ("source_run_id", "run_id", "observed_at")
            if run.get(field) is not None
        }
    return result


def main() -> None:
    app(prog_name="compute-bazaar")


if __name__ == "__main__":
    main()
