"""Bounded FastAPI interface to the Compute Bazaar Gold query layer."""

from __future__ import annotations

import argparse
import os
from typing import Annotated, Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from .market_query_service import MarketQueryService
from .prices.query_catalog import MAX_QUERY_LIMIT


DEFAULT_LAKE_ROOT = "data/lake"
MAX_SQL_LENGTH = 10_000
Limit = Annotated[int, Query(ge=1, le=MAX_QUERY_LIMIT)]


class ScratchQueryRequest(BaseModel):
    sql: str = Field(min_length=1, max_length=MAX_SQL_LENGTH)
    limit: int = Field(default=100, ge=1, le=MAX_QUERY_LIMIT)


def create_app(
    *,
    lake_root: str | None = None,
    enable_scratch_sql: bool | None = None,
) -> FastAPI:
    selected_root = lake_root or os.getenv(
        "COMPUTE_BAZAAR_LAKE_ROOT", DEFAULT_LAKE_ROOT
    )
    scratch_sql_enabled = (
        enable_scratch_sql
        if enable_scratch_sql is not None
        else os.getenv("COMPUTE_BAZAAR_ENABLE_SCRATCH_SQL", "").lower()
        in {"1", "true", "yes"}
    )
    service = MarketQueryService(lake_root=selected_root)
    app = FastAPI(
        title="Compute Bazaar Query API",
        version="0.1.0",
        description="Read-only DataFusion queries over the latest complete Gold run.",
    )
    app.state.query_service = service

    @app.get("/healthz")
    def health() -> dict[str, Any]:
        try:
            manifest = service.manifest()
        except Exception as exc:  # noqa: BLE001 - converted to a stable health payload.
            return {"status": "unavailable", "detail": str(exc)}
        return {"status": "ok", "run_id": manifest["run_id"]}

    @app.get("/v1/manifest")
    def manifest() -> dict[str, Any]:
        return _api_call(service.manifest)

    @app.get("/v1/catalog")
    def catalog() -> dict[str, Any]:
        return _api_call(service.catalog)

    @app.get("/v1/queries/{query_id}")
    def saved_query(
        query_id: str,
        limit: Limit = 100,
        version: str | None = None,
    ) -> dict[str, Any]:
        return _api_call(
            service.saved_query,
            query_id=query_id,
            version=version,
            limit=limit,
        )

    if scratch_sql_enabled:

        @app.post("/v1/sql")
        def scratch_sql(request: ScratchQueryRequest) -> dict[str, Any]:
            return _api_call(
                service.scratch_sql,
                sql=request.sql,
                limit=request.limit,
            )

    @app.get("/v1/benchmarks")
    def benchmarks(
        family: str | None = None,
        limit: Limit = 20,
    ) -> dict[str, Any]:
        return _api_call(service.benchmarks, family=family, limit=limit)

    @app.get("/v1/listings")
    def listings(
        gpu_model: str | None = None,
        provider: str | None = None,
        limit: Limit = 100,
    ) -> dict[str, Any]:
        return _api_call(
            service.listings,
            gpu_model=gpu_model,
            provider=provider,
            limit=limit,
        )

    @app.get("/v1/providers")
    def providers(
        gpu_model: str | None = None,
        limit: Limit = 100,
    ) -> dict[str, Any]:
        return _api_call(service.providers, gpu_model=gpu_model, limit=limit)

    @app.get("/v1/prime/offers")
    def prime_offers(family: str | None = None) -> dict[str, Any]:
        return _api_call(service.prime_offers, family=family)

    return app


def _api_call(function: Any, /, **kwargs: Any) -> Any:
    try:
        return function(**kwargs)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc).strip("'")) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (FileNotFoundError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve read-only Compute Bazaar Gold queries")
    parser.add_argument(
        "--lake-root",
        default=os.getenv("COMPUTE_BAZAAR_LAKE_ROOT", DEFAULT_LAKE_ROOT),
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument(
        "--enable-scratch-sql",
        action="store_true",
        help="Expose the bounded read-only SQL workbench endpoint",
    )
    args = parser.parse_args()

    import uvicorn

    uvicorn.run(
        create_app(
            lake_root=args.lake_root,
            enable_scratch_sql=args.enable_scratch_sql,
        ),
        host=args.host,
        port=args.port,
    )


app = create_app()


if __name__ == "__main__":
    main()
