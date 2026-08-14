"""Object paths and writes for the market lake."""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.fs as pafs
import pyarrow.parquet as pq


class MarketLake:
    def __init__(self, root: str | Path) -> None:
        self.root = str(root).rstrip("/")

    def bronze_ref(self, *, source: str, day: date, source_run_id: str) -> str:
        return self._ref(
            "bronze",
            f"source={source}",
            f"date={day.isoformat()}",
            f"source_run_id={source_run_id}",
            "response.json",
        )

    def silver_ref(self, *, source: str, day: date, source_run_id: str) -> str:
        return self._ref(
            "silver",
            "gpu_offers",
            f"date={day.isoformat()}",
            f"source={source}",
            f"source_run_id={source_run_id}",
            "part-0.parquet",
        )

    def manifest_ref(self, *, source: str, day: date, source_run_id: str) -> str:
        return self._ref(
            "runs",
            f"source={source}",
            f"date={day.isoformat()}",
            f"source_run_id={source_run_id}",
            "manifest.json",
        )

    def market_manifest_ref(self, *, day: date, generation_id: str) -> str:
        return self._ref(
            "_manifests",
            "market",
            f"date={day.isoformat()}",
            f"generation_id={generation_id}.json",
        )

    def latest_market_manifest_ref(self) -> str:
        return self._ref("_manifests", "market", "latest.json")

    def write_json(self, ref: str, value: Any) -> str:
        data = json.dumps(
            value,
            default=_json_default,
            indent=2,
            sort_keys=True,
        ).encode()
        filesystem, path = _filesystem(ref)
        _ensure_parent(filesystem, path)
        if isinstance(filesystem, pafs.LocalFileSystem):
            target = Path(path)
            temporary = target.with_suffix(target.suffix + ".tmp")
            temporary.write_bytes(data)
            temporary.replace(target)
        else:
            with filesystem.open_output_stream(path) as stream:
                stream.write(data)
        return ref

    def write_parquet(
        self,
        ref: str,
        rows: Iterable[Mapping[str, Any]],
        *,
        schema: pa.Schema,
    ) -> str:
        table = pa.Table.from_pylist([dict(row) for row in rows], schema=schema)
        filesystem, path = _filesystem(ref)
        _ensure_parent(filesystem, path)
        if isinstance(filesystem, pafs.LocalFileSystem):
            target = Path(path)
            temporary = target.with_suffix(target.suffix + ".tmp")
            pq.write_table(table, temporary)
            temporary.replace(target)
        else:
            with filesystem.open_output_stream(path) as stream:
                pq.write_table(table, stream)
        return ref

    def _ref(self, *parts: str) -> str:
        suffix = "/".join(part.strip("/") for part in parts)
        return f"{self.root}/{suffix}"


def _filesystem(ref: str) -> tuple[pafs.FileSystem, str]:
    if "://" in ref:
        return pafs.FileSystem.from_uri(ref)
    return pafs.LocalFileSystem(), str(Path(ref).resolve())


def _ensure_parent(filesystem: pafs.FileSystem, path: str) -> None:
    parent = path.rsplit("/", 1)[0]
    if parent:
        filesystem.create_dir(parent, recursive=True)


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, tuple):
        return list(value)
    raise TypeError(f"Cannot encode {type(value).__name__}")


def default_market_lake_root() -> str:
    configured = os.getenv("COMPUTE_BAZAAR_MARKET_HOME")
    if configured:
        return str(Path(configured).expanduser())
    data_home = Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return str(data_home / "compute-bazaar" / "market")
