"""DataFusion and Perspective workspace for the Compute Bazaar Terminal."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from threading import BoundedSemaphore, Lock
from time import perf_counter
from typing import Any

import pyarrow as pa
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from ..analysis_store import AnalysisStore, blueprint_payload, model_payload
from ..data_catalog import ComputeBazaarCatalog
from ..operations import OperationalLedger
from ..prices.gold_manifest import read_latest_gold_manifest
from ..prices.query_catalog import MAX_QUERY_LIMIT, load_query_catalog
from .views import TERMINAL_VIEWS


MAX_SQL_LENGTH = 10_000


class DataQuery(BaseModel):
    sql: str = Field(min_length=1, max_length=MAX_SQL_LENGTH)
    limit: int = Field(default=500, ge=1, le=MAX_QUERY_LIMIT)


class AnalysisSave(BaseModel):
    title: str = Field(min_length=1, max_length=96)
    description: str = Field(default="", max_length=500)
    sql: str = Field(min_length=1, max_length=MAX_SQL_LENGTH)
    limit: int = Field(default=500, ge=1, le=MAX_QUERY_LIMIT)
    perspective: dict[str, Any]
    model_id: str | None = None
    blueprint_id: str | None = None


class CatalogStore:
    """Keep one DataFusion catalog per immutable lake generation."""

    def __init__(self, lake_root: str) -> None:
        self._lake_root = lake_root
        self._operations = OperationalLedger()
        self._lock = Lock()
        self._catalog = ComputeBazaarCatalog(
            lake_root=lake_root,
            operations=self._operations,
        )
        self._operations_version = self._operations.version()

    def current(self) -> ComputeBazaarCatalog:
        manifest = read_latest_gold_manifest(self._lake_root)
        run_id = manifest.get("run_id")
        operations_version = self._operations.version()
        with self._lock:
            if (
                run_id != self._catalog.manifest.get("run_id")
                or operations_version != self._operations_version
            ):
                self._catalog = ComputeBazaarCatalog(
                    lake_root=self._lake_root,
                    manifest=manifest,
                    operations=self._operations,
                )
                self._operations_version = self._operations.version()
            return self._catalog


class DataWorkspace:
    def __init__(
        self,
        *,
        lake_root: str,
        asset_root: Path,
        initial_view: str | None = None,
        initial_query: str | None = None,
        initial_sql: str | None = None,
        initial_limit: int = 500,
        initial_perspective: dict[str, Any] | None = None,
    ) -> None:
        self.catalogs = CatalogStore(lake_root)
        self.asset_root = asset_root
        self.initial_view = initial_view
        self.initial_query = initial_query
        self.initial_sql = initial_sql
        self.initial_limit = initial_limit
        self.initial_perspective = initial_perspective
        self.analyses = AnalysisStore()
        self._query_slot = BoundedSemaphore(value=1)

    def status(self) -> dict[str, Any]:
        tables = self.catalogs.current().tables()
        return {
            "available": True,
            "href": "/data",
            "run": tables["run"],
            "table_count": len(tables["tables"]),
        }

    def register(self, app: FastAPI) -> None:
        @app.get("/data", include_in_schema=False)
        def data() -> FileResponse:
            return FileResponse(self.asset_root / "index.html")

        @app.get("/api/data/session")
        def session() -> dict[str, Any]:
            catalog = self.catalogs.current()
            table_payload = catalog.tables()
            queries = []
            for query in load_query_catalog():
                entry = query.catalog_entry(catalog.manifest)
                entry["sql"] = _qualified_gold_sql(query.sql, query.tables)
                queries.append(entry)
            queries_by_id = {query["query_id"]: query for query in queries}
            table_refs = {
                f"{table['layer']}.{table['table_name']}"
                for table in table_payload["tables"]
            }
            models = []
            models_by_id = {}
            for model in self.analyses.list_models():
                entry = model_payload(model)
                missing = sorted(set(model.tables) - table_refs)
                entry["available"] = not missing
                entry["missing_tables"] = missing
                models.append(entry)
                models_by_id[model.model_id] = entry
            blueprints = []
            for blueprint in self.analyses.list_blueprints():
                entry = blueprint_payload(blueprint)
                model = models_by_id[blueprint.model_id]
                entry["available"] = model["available"]
                entry["missing_tables"] = model["missing_tables"]
                entry["sql"] = model["sql"]
                entry["default_limit"] = model["default_limit"]
                blueprints.append(entry)
            views = []
            for blueprint in TERMINAL_VIEWS:
                entry = blueprint.as_dict()
                query = queries_by_id.get(blueprint.query_id or "")
                if query:
                    entry["available"] = bool(query["available"])
                    entry["sql"] = query["sql"]
                    entry["default_limit"] = query["default_limit"]
                else:
                    entry["available"] = bool(
                        blueprint.sql
                        and all(table in table_refs for table in blueprint.tables)
                    )
                views.append(entry)
            return {
                "contract": "compute-bazaar.data.session",
                "run": table_payload["run"],
                "tables": table_payload["tables"],
                "queries": queries,
                "views": views,
                "models": models,
                "blueprints": blueprints,
                "launch": _launch_payload(
                    initial_view=self.initial_view,
                    initial_query=self.initial_query,
                    initial_sql=self.initial_sql,
                    initial_limit=self.initial_limit,
                    initial_perspective=self.initial_perspective,
                ),
                "limits": {"default": 500, "maximum": MAX_QUERY_LIMIT},
            }

        @app.post("/api/data/analyses")
        def save_analysis(request: AnalysisSave) -> dict[str, Any]:
            catalog = self.catalogs.current()
            try:
                catalog.query_arrow(request.sql, limit=1)
                model, blueprint = self.analyses.save_analysis(
                    title=request.title,
                    description=request.description,
                    sql=request.sql,
                    default_limit=request.limit,
                    perspective=request.perspective,
                    model_id=request.model_id,
                    blueprint_id=request.blueprint_id,
                )
            except (FileNotFoundError, ValueError) as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            return {
                "model": model_payload(model),
                "blueprint": blueprint_payload(blueprint),
            }

        @app.delete("/api/data/blueprints/{blueprint_id}", status_code=204)
        def delete_blueprint(blueprint_id: str) -> Response:
            try:
                self.analyses.delete_blueprint(blueprint_id)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            return Response(status_code=204)

        @app.get("/api/data/tables/{layer}/{table_name}")
        def describe_table(layer: str, table_name: str) -> dict[str, Any]:
            catalog = self.catalogs.current()
            try:
                return catalog.describe(f"{layer}.{table_name}")
            except (KeyError, ValueError) as exc:
                raise HTTPException(
                    status_code=404,
                    detail=str(exc).strip("'"),
                ) from exc

        @app.post("/api/data/query")
        def query(request: DataQuery) -> Response:
            if not self._query_slot.acquire(blocking=False):
                raise HTTPException(
                    status_code=429,
                    detail="A query is already running",
                )
            started = perf_counter()
            try:
                catalog = self.catalogs.current()
                table, selected_limit = catalog.query_arrow(
                    request.sql,
                    limit=request.limit,
                )
                payload = _arrow_stream(table)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            except (FileNotFoundError, RuntimeError) as exc:
                raise HTTPException(
                    status_code=503,
                    detail="Data is unavailable",
                ) from exc
            finally:
                self._query_slot.release()

            elapsed_ms = round((perf_counter() - started) * 1000, 1)
            run = _run_identity(catalog)
            return Response(
                content=payload,
                media_type="application/vnd.apache.arrow.stream",
                headers={
                    "Cache-Control": "no-store",
                    "X-Compute-Bazaar-Run-Id": str(run.get("run_id") or ""),
                    "X-Compute-Bazaar-Observed-At": str(run.get("observed_at") or ""),
                    "X-Compute-Bazaar-Row-Count": str(table.num_rows),
                    "X-Compute-Bazaar-Query-Limit": str(selected_limit),
                    "X-Compute-Bazaar-Elapsed-Ms": str(elapsed_ms),
                    "X-Compute-Bazaar-Query-Hash": hashlib.sha256(
                        request.sql.encode("utf-8")
                    ).hexdigest()[:12],
                },
            )

        @app.get("/api/data/offers")
        def offers(
            provider: str | None = None,
            gpu_model: str | None = None,
            offer_id: str | None = None,
            include_unavailable: bool = False,
            limit: int = Query(default=100, ge=1, le=MAX_QUERY_LIMIT),
        ) -> Response:
            from ..offers import OfferService, OfferServiceError, display_row

            started = perf_counter()
            try:
                service = OfferService.from_environment()
                if offer_id:
                    offer = service.inspect(offer_id)
                    rows = [display_row(offer)]
                    observed_at = offer.observed_at
                    batch_id = offer.batch_id or "provider-read"
                else:
                    result = service.list_offers(
                        providers=[provider] if provider else None,
                        gpu_model=gpu_model,
                        include_unavailable=include_unavailable,
                        limit=limit,
                    )
                    rows = [display_row(row) for row in result.observations]
                    observed_at = result.observed_at
                    batch_id = result.batch_id
                    if not rows:
                        failed = [
                            status.message or status.status
                            for status in result.providers
                            if status.status != "ok"
                        ]
                        detail = "; ".join(failed) or "No current offers match"
                        raise OfferServiceError(detail)
                table = pa.Table.from_pylist(rows)
                payload = _arrow_stream(table)
            except OfferServiceError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            return Response(
                content=payload,
                media_type="application/vnd.apache.arrow.stream",
                headers={
                    "Cache-Control": "no-store",
                    "X-Compute-Bazaar-Run-Id": batch_id,
                    "X-Compute-Bazaar-Observed-At": observed_at.isoformat(),
                    "X-Compute-Bazaar-Row-Count": str(table.num_rows),
                    "X-Compute-Bazaar-Elapsed-Ms": str(
                        round((perf_counter() - started) * 1000, 1)
                    ),
                },
            )

        @app.get("/api/data/launch-plan")
        def launch_plan(
            offer_id: str,
            name: str | None = None,
            image: str | None = None,
            ssh_key_id: str | None = None,
            disk_gb: int = Query(default=50, ge=1),
            volume_gb: int = Query(default=0, ge=0),
        ) -> Response:
            from ..offers import OfferServiceError
            from ..provisioning import LaunchPlanner

            started = perf_counter()
            try:
                plan = LaunchPlanner.from_environment().plan(
                    offer_id,
                    name=name,
                    image=image,
                    ssh_key_ids=(ssh_key_id,) if ssh_key_id else (),
                    disk_gb=disk_gb,
                    volume_gb=volume_gb,
                )
                table = pa.Table.from_pylist([plan.row()])
                payload = _arrow_stream(table)
            except (OfferServiceError, ValueError) as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            return Response(
                content=payload,
                media_type="application/vnd.apache.arrow.stream",
                headers={
                    "Cache-Control": "no-store",
                    "X-Compute-Bazaar-Run-Id": plan.plan_id,
                    "X-Compute-Bazaar-Observed-At": plan.observed_at.isoformat(),
                    "X-Compute-Bazaar-Row-Count": "1",
                    "X-Compute-Bazaar-Elapsed-Ms": str(
                        round((perf_counter() - started) * 1000, 1)
                    ),
                    "X-Compute-Bazaar-Submitted": "false",
                },
            )


def _launch_payload(
    *,
    initial_view: str | None,
    initial_query: str | None,
    initial_sql: str | None,
    initial_limit: int,
    initial_perspective: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if initial_sql:
        return {
            "kind": "sql",
            "sql": initial_sql,
            "limit": initial_limit,
            "perspective": initial_perspective,
        }
    if initial_query:
        return {
            "kind": "query",
            "query_id": initial_query,
            "limit": initial_limit,
        }
    if initial_view:
        return {"kind": "view", "view_id": initial_view}
    return None


def _run_identity(catalog: ComputeBazaarCatalog) -> dict[str, Any]:
    return {
        "run_id": catalog.manifest.get("run_id"),
        "observed_at": catalog.manifest.get("observed_at"),
    }


def _arrow_stream(table: pa.Table) -> bytes:
    table = _perspective_compatible(table)
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, table.schema) as writer:
        writer.write_table(table)
    return sink.getvalue().to_pybytes()


def _perspective_compatible(table: pa.Table) -> pa.Table:
    """Use stable Arrow scalar types at the browser transport boundary."""
    columns: list[pa.ChunkedArray] = []
    fields: list[pa.Field] = []
    for field, column in zip(table.schema, table.columns, strict=True):
        target_type = field.type
        if pa.types.is_string_view(target_type):
            target_type = pa.string()
        elif pa.types.is_binary_view(target_type):
            target_type = pa.binary()
        columns.append(
            column.cast(target_type) if target_type != field.type else column
        )
        fields.append(
            pa.field(
                field.name,
                target_type,
                nullable=field.nullable,
                metadata=field.metadata,
            )
        )
    schema = pa.schema(fields, metadata=table.schema.metadata)
    return pa.Table.from_arrays(columns, schema=schema)


def _qualified_gold_sql(sql: str, tables: tuple[str, ...]) -> str:
    statement = sql
    for table_name in sorted(tables, key=len, reverse=True):
        statement = re.sub(
            rf"(?<![A-Za-z0-9_.]){re.escape(table_name)}(?![A-Za-z0-9_])",
            f"gold.{table_name}",
            statement,
        )
    return statement
