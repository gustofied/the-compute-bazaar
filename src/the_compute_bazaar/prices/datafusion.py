"""DataFusion helpers for GPU market benchmarks."""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from typing import Any
from urllib.parse import urlparse


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


DEFAULT_PRICE_INDEX_SQL = """
with usable_offers as (
  select
    provider,
    gpu_model,
    source_offer_id,
    observed_at,
    price_usd_hr,
    case
      when gpu_count is not null and gpu_count > 0 then price_usd_hr / gpu_count
      else price_usd_hr
    end as unit_price_usd_hr,
    gpu_count,
    country,
    region,
    is_secure,
    is_spot
  from gpu_offers
  where price_usd_hr > 0
    and availability_status = 'available'
)
select
  gpu_model,
  min(unit_price_usd_hr) as executable_floor_usd_gpu_hr,
  avg(unit_price_usd_hr) as simple_mean_usd_gpu_hr,
  min(price_usd_hr) as cheapest_offer_usd_hr,
  count(*) as offer_count,
  count(distinct provider) as provider_count,
  count(distinct country) as country_count,
  sum(case when is_secure then 1 else 0 end) as secure_offer_count,
  sum(case when is_spot then 1 else 0 end) as spot_offer_count,
  max(observed_at) as latest_observed_at
from usable_offers
group by gpu_model
order by executable_floor_usd_gpu_hr asc, offer_count desc
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
    _register_object_stores(ctx, [parquet_uri])
    ctx.register_parquet(table_name, parquet_uri)
    batches = ctx.sql(sql).collect()
    if not batches:
        return []
    return pa.Table.from_batches(batches).to_pylist()


def query_price_index(*, parquet_uri: str, limit: int | None = None) -> list[dict[str, Any]]:
    sql = DEFAULT_PRICE_INDEX_SQL
    if limit is not None:
        sql = f"{sql.rstrip()}\nlimit {int(limit)}"
    return query_parquet(parquet_uri=parquet_uri, table_name="gpu_offers", sql=sql)


def query_tables(*, tables: Mapping[str, str], sql: str) -> list[dict[str, Any]]:
    try:
        import pyarrow as pa
        from datafusion import SessionContext
    except ImportError as exc:
        raise RuntimeError("DataFusion queries require the 'platform' extra: uv sync --extra platform") from exc

    ctx = SessionContext()
    _register_object_stores(ctx, tables.values())
    for table_name, parquet_uri in tables.items():
        ctx.register_parquet(table_name, parquet_uri)
    batches = ctx.sql(sql).collect()
    if not batches:
        return []
    return pa.Table.from_batches(batches).to_pylist()


def _register_object_stores(ctx: Any, uris: Iterable[str]) -> None:
    s3_buckets = {urlparse(uri).netloc for uri in uris if uri.startswith("s3://")}
    if not s3_buckets:
        return

    try:
        import boto3
        from datafusion.object_store import AmazonS3
    except ImportError as exc:
        raise RuntimeError("Querying s3:// paths requires boto3 and DataFusion S3 support") from exc

    session = boto3.Session(
        profile_name=os.getenv("AWS_PROFILE"),
        region_name=os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION"),
    )
    credentials = session.get_credentials()
    if credentials is None:
        raise RuntimeError("No AWS credentials available for DataFusion S3 query")

    frozen = credentials.get_frozen_credentials()
    region = session.region_name or "us-east-1"
    for bucket in sorted(s3_buckets):
        kwargs: dict[str, Any] = {
            "bucket_name": bucket,
            "region": region,
            "access_key_id": frozen.access_key,
            "secret_access_key": frozen.secret_key,
        }
        if frozen.token:
            kwargs["session_token"] = frozen.token
        ctx.register_object_store("s3://", AmazonS3(**kwargs), host=bucket)
