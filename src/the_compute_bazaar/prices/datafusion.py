"""DataFusion helpers for GPU market benchmarks."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


DEFAULT_BENCHMARK_SQL = """
select
  gpu_model,
  min(price_usd_hr) as executable_floor,
  avg(price_usd_hr) as simple_mean_price,
  count(*) as offer_count,
  count(distinct provider) as provider_count
from gpu_offers
where price_usd_hr > 0
  and availability_status = 'available'
group by gpu_model
order by gpu_model
"""


def query_parquet(
    *,
    parquet_uri: str,
    sql: str,
    table_name: str = "gpu_offers",
) -> list[dict[str, Any]]:
    try:
        import pyarrow as pa
        from datafusion import SessionContext
    except ImportError as exc:
        raise RuntimeError("DataFusion queries require the 'platform' extra: uv sync --extra platform") from exc

    ctx = SessionContext()
    ctx.register_parquet(table_name, parquet_uri)
    batches = ctx.sql(sql).collect()
    if not batches:
        return []
    return pa.Table.from_batches(batches).to_pylist()


def query_tables(*, tables: Mapping[str, str], sql: str) -> list[dict[str, Any]]:
    try:
        import pyarrow as pa
        from datafusion import SessionContext
    except ImportError as exc:
        raise RuntimeError("DataFusion queries require the 'platform' extra: uv sync --extra platform") from exc

    ctx = SessionContext()
    for table_name, parquet_uri in tables.items():
        ctx.register_parquet(table_name, parquet_uri)
    batches = ctx.sql(sql).collect()
    if not batches:
        return []
    return pa.Table.from_batches(batches).to_pylist()

