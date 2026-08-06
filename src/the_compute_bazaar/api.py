"""Bounded FastAPI interface to the Compute Bazaar Gold query layer."""

from __future__ import annotations

import argparse
import hmac
import os
from threading import BoundedSemaphore
from typing import Annotated, Any

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .data_root import resolve_lake_root
from .market_query_service import MarketQueryService
from .prices.query_catalog import MAX_QUERY_LIMIT


MAX_SQL_LENGTH = 10_000
Limit = Annotated[int, Query(ge=1, le=MAX_QUERY_LIMIT)]


class ScratchQueryRequest(BaseModel):
    sql: str = Field(min_length=1, max_length=MAX_SQL_LENGTH)
    limit: int = Field(default=100, ge=1, le=MAX_QUERY_LIMIT)


def create_app(
    *,
    lake_root: str | None = None,
    enable_scratch_sql: bool | None = None,
    query_api_key: str | None = None,
) -> FastAPI:
    selected_lake = resolve_lake_root(lake_root)
    selected_root = selected_lake.root
    scratch_sql_enabled = (
        enable_scratch_sql
        if enable_scratch_sql is not None
        else os.getenv("COMPUTE_BAZAAR_ENABLE_SCRATCH_SQL", "").lower()
        in {"1", "true", "yes"}
    )
    scratch_api_key = query_api_key or os.getenv("COMPUTE_BAZAAR_QUERY_API_KEY")
    if scratch_sql_enabled and not scratch_api_key:
        raise RuntimeError("Scratch SQL requires COMPUTE_BAZAAR_QUERY_API_KEY")
    service = MarketQueryService(lake_root=selected_root)
    scratch_query_slot = BoundedSemaphore(value=1)
    app = FastAPI(
        title="Compute Bazaar Query API",
        description="Read-only DataFusion queries over the latest complete Gold run.",
    )
    app.state.query_service = service
    app.state.data_source = selected_lake

    @app.get("/healthz")
    def health() -> Any:
        try:
            manifest = service.manifest()
        except Exception:  # noqa: BLE001 - health never exposes storage details.
            return JSONResponse(
                status_code=503,
                content={"status": "unavailable"},
            )
        return {"status": "ok", "run_id": manifest["run_id"]}

    @app.get("/manifest")
    def manifest() -> dict[str, Any]:
        return _api_call(service.manifest)

    @app.get("/catalog")
    def catalog() -> dict[str, Any]:
        return _api_call(service.catalog)

    @app.get("/queries/{query_id}")
    def saved_query(
        query_id: str,
        limit: Limit = 100,
    ) -> dict[str, Any]:
        return _api_call(
            service.saved_query,
            query_id=query_id,
            limit=limit,
        )

    if scratch_sql_enabled:

        @app.post("/sql")
        def scratch_sql(
            request: ScratchQueryRequest,
            authorization: Annotated[str | None, Header()] = None,
        ) -> dict[str, Any]:
            _require_bearer_token(authorization, expected=str(scratch_api_key))
            if not scratch_query_slot.acquire(blocking=False):
                raise HTTPException(
                    status_code=429,
                    detail="Another scratch query is already running",
                )
            try:
                return _api_call(
                    service.scratch_sql,
                    sql=request.sql,
                    limit=request.limit,
                )
            finally:
                scratch_query_slot.release()

    @app.get("/gpu-price-index")
    def gpu_price_index(
        family: str | None = None,
        history: bool = False,
        limit: Limit = 20,
    ) -> dict[str, Any]:
        return _api_call(
            service.gpu_price_index,
            family=family,
            history=history,
            limit=limit,
        )

    @app.get("/gpu-availability")
    def gpu_availability(
        gpu_model: str | None = None,
        measurement_kind: str | None = None,
        history: bool = False,
        limit: Limit = 100,
    ) -> dict[str, Any]:
        return _api_call(
            service.gpu_availability,
            gpu_model=gpu_model,
            measurement_kind=measurement_kind,
            history=history,
            limit=limit,
        )

    @app.get("/listings")
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

    @app.get("/providers")
    def providers(
        gpu_model: str | None = None,
        limit: Limit = 100,
    ) -> dict[str, Any]:
        return _api_call(service.providers, gpu_model=gpu_model, limit=limit)

    @app.get("/prime/offers")
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
        raise HTTPException(
            status_code=503,
            detail="Market data is unavailable",
        ) from exc


def _require_bearer_token(value: str | None, *, expected: str) -> None:
    scheme, _, token = (value or "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="Invalid API token")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Serve read-only Compute Bazaar Gold queries"
    )
    parser.add_argument(
        "--lake-root",
        default=None,
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
