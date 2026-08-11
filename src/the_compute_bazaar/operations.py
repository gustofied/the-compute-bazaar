"""Private offer, allocation, and Fleet history."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .fleet.registry import FleetRegistry, default_fleet_root

if TYPE_CHECKING:
    import pyarrow as pa

    from .fleet.models import FleetDoctorResult, FleetInspection, FleetMachine
    from .offers import OfferBatch
    from .provider_execution import LaunchReceipt
    from .provisioning import LaunchPlan


SCHEMA = """
create table if not exists offer_observations (
  observation_id text primary key,
  batch_id text not null,
  market_run_id text,
  observation_purpose text not null,
  observation_resolution text not null,
  selection_resolution text not null,
  observed_at text not null,
  provider text not null,
  source_connector text not null,
  source_offer_id text not null,
  gpu_raw_name text not null,
  gpu_model text not null,
  gpu_count integer not null,
  vram_gb real,
  price_usd_instance_hr real not null,
  price_usd_gpu_hr real not null,
  currency text not null,
  available_gpu_count_lower_bound integer,
  is_available integer,
  source_availability_status text not null,
  source_stock_status text,
  country text,
  region text,
  cloud_type text,
  location_ids_json text not null,
  selection_fingerprint text,
  native_selection_json text not null,
  query_scope_json text not null,
  response_complete integer not null,
  is_spot integer,
  is_secure integer,
  gpu_socket text,
  price_is_variable integer,
  minimum_executable_price_usd_instance_hr real,
  required_resource_price_usd_instance_hr real,
  price_basis text,
  raw_ref text,
  raw_hash text,
  source_run_id text,
  source_manifest_ref text,
  source_normalized_ref text,
  methodology_version text not null,
  schema_version text not null
);

create table if not exists fleet_allocations (
  host_id text primary key,
  provider text not null,
  provider_resource_id text not null,
  offer_observation_id text not null,
  offer_batch_id text not null,
  offer_id text not null,
  plan_id text not null,
  name text not null,
  cloud_type text not null,
  location text not null,
  state text not null,
  gpu_family text,
  gpu_model text not null,
  gpu_count integer not null,
  selected_price_usd_gpu_hr real not null,
  selected_price_usd_instance_hr real not null,
  offer_observed_at text not null,
  launched_at text not null,
  terminate_at text not null,
  terminated_at text,
  expected_max_cost_usd real not null,
  ssh_ready integer not null,
  updated_at text not null
);

create table if not exists fleet_observations (
  observation_id text primary key,
  host_id text not null,
  provider text not null,
  observed_at text not null,
  readiness text,
  gpu_count_detected integer not null,
  gpu_utilization_pct real,
  gpu_memory_used_mb integer,
  gpu_memory_total_mb integer,
  gpu_temperature_c integer,
  cpu_utilization_pct real,
  memory_used_mb integer,
  memory_mb integer,
  disk_free_gb integer,
  driver_versions text,
  driver_cuda_version text,
  cuda_toolkit_version text,
  inspection_json text not null,
  checks_json text
);
"""


class OperationalLedger:
    def __init__(
        self,
        path: Path | None = None,
        *,
        registry: FleetRegistry | None = None,
    ) -> None:
        self.path = (path or default_fleet_root() / "operations.sqlite3").expanduser()
        self.registry = registry or FleetRegistry(self.path.parent)

    def version(self) -> tuple[int, int, int]:
        return (
            _mtime(self.path),
            _mtime(Path(f"{self.path}-wal")),
            _mtime(self.registry.path),
        )

    def record_offer_observations(self, batch: OfferBatch) -> None:
        rows = []
        for observation in batch.observations:
            row = observation.row()
            if not row["observation_id"]:
                raise ValueError("Direct offer observation has no observation_id")
            rows.append(row)
        if rows:
            self._insert("offer_observations", rows, ignore=True)

    def record_launch(self, plan: LaunchPlan, receipt: LaunchReceipt) -> None:
        machine = receipt.machine
        now = _timestamp(datetime.now(UTC))
        row = {
            "host_id": machine.host_id,
            "provider": machine.provider,
            "provider_resource_id": machine.provider_resource_id,
            "offer_observation_id": plan.offer_observation_id,
            "offer_batch_id": plan.offer_batch_id,
            "offer_id": plan.offer_id,
            "plan_id": plan.plan_id,
            "name": machine.name,
            "cloud_type": plan.cloud_type,
            "location": plan.location,
            "state": machine.state,
            "gpu_family": _gpu_family(machine.gpu_model),
            "gpu_model": machine.gpu_model,
            "gpu_count": machine.gpu_count,
            "selected_price_usd_gpu_hr": machine.price_usd_gpu_hr,
            "selected_price_usd_instance_hr": machine.price_usd_instance_hr,
            "offer_observed_at": _timestamp(plan.observed_at),
            "launched_at": _timestamp(receipt.launched_at),
            "terminate_at": _timestamp(receipt.terminate_at),
            "terminated_at": None,
            "expected_max_cost_usd": receipt.expected_max_cost_usd,
            "ssh_ready": machine.ssh is not None,
            "updated_at": now,
        }
        self._insert("fleet_allocations", [row], replace=True)

    def record_machine_state(
        self,
        machine: FleetMachine,
        *,
        occurred_at: datetime | None = None,
    ) -> None:
        when = occurred_at or datetime.now(UTC)
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
update fleet_allocations
set state = ?, ssh_ready = ?,
    terminated_at = case when ? = 'terminated' then ? else terminated_at end,
    updated_at = ?
where host_id = ?
""",
                (
                    machine.state,
                    int(machine.ssh is not None),
                    machine.state,
                    _timestamp(when),
                    _timestamp(when),
                    machine.host_id,
                ),
            )

    def record_inspection(
        self,
        inspection: FleetInspection,
        doctor: FleetDoctorResult | None = None,
    ) -> None:
        gpus = inspection.gpus
        row = {
            "observation_id": _identity(
                inspection.machine.host_id, inspection.observed_at.isoformat()
            ),
            "host_id": inspection.machine.host_id,
            "provider": inspection.machine.provider,
            "observed_at": _timestamp(inspection.observed_at),
            "readiness": doctor.readiness if doctor else None,
            "gpu_count_detected": len(gpus),
            "gpu_utilization_pct": _average(gpu.utilization_pct for gpu in gpus),
            "gpu_memory_used_mb": sum(gpu.memory_used_mb for gpu in gpus)
            if gpus
            else None,
            "gpu_memory_total_mb": sum(gpu.memory_total_mb for gpu in gpus)
            if gpus
            else None,
            "gpu_temperature_c": max(
                (gpu.temperature_c for gpu in gpus if gpu.temperature_c is not None),
                default=None,
            ),
            "cpu_utilization_pct": inspection.cpu_utilization_pct,
            "memory_used_mb": inspection.memory_used_mb,
            "memory_mb": inspection.memory_mb,
            "disk_free_gb": inspection.disk_free_gb,
            "driver_versions": ",".join(sorted({gpu.driver_version for gpu in gpus})),
            "driver_cuda_version": inspection.driver_cuda_version,
            "cuda_toolkit_version": inspection.cuda_toolkit_version,
            "inspection_json": _json(inspection.model_dump(mode="json")),
            "checks_json": _json(doctor.payload()) if doctor else None,
        }
        self._insert("fleet_observations", [row], replace=True)

    def arrow_tables(self) -> dict[str, pa.Table]:
        import pyarrow as pa

        definitions = {
            "offer_observations": _offer_schema(pa),
            "fleet_allocations": _allocation_schema(pa),
            "fleet_observations": _fleet_observation_schema(pa),
        }
        with closing(self._connect()) as connection:
            tables = {
                name: _arrow_table(connection, f"select * from {table}", schema)
                for name, table, schema in (
                    (
                        "offer_observations",
                        "offer_observations",
                        definitions["offer_observations"],
                    ),
                    (
                        "fleet_allocations",
                        "fleet_allocations",
                        definitions["fleet_allocations"],
                    ),
                    (
                        "fleet_observations",
                        "fleet_observations",
                        definitions["fleet_observations"],
                    ),
                )
            }
        tables["fleet_machines"] = pa.Table.from_pylist(
            [_machine_row(machine) for machine in self.registry.list()],
            schema=_machine_schema(pa),
        )
        return tables

    def _insert(
        self,
        table: str,
        rows: list[dict[str, Any]],
        *,
        ignore: bool = False,
        replace: bool = False,
    ) -> None:
        columns = tuple(rows[0])
        mode = "replace" if replace else "ignore" if ignore else "abort"
        sql = (
            f"insert or {mode} into {table} ({', '.join(columns)}) "
            f"values ({', '.join('?' for _ in columns)})"
        )
        values = [tuple(_sqlite(row[column]) for column in columns) for row in rows]
        with closing(self._connect()) as connection, connection:
            connection.executemany(sql, values)

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("pragma journal_mode=wal")
        connection.execute("pragma busy_timeout=5000")
        connection.executescript(SCHEMA)
        return connection


def _arrow_table(
    connection: sqlite3.Connection, sql: str, schema: pa.Schema
) -> pa.Table:
    import pyarrow as pa

    rows = [dict(row) for row in connection.execute(sql).fetchall()]
    timestamps = {field.name for field in schema if pa.types.is_timestamp(field.type)}
    booleans = {field.name for field in schema if pa.types.is_boolean(field.type)}
    for row in rows:
        for name in timestamps:
            row[name] = datetime.fromisoformat(row[name]) if row.get(name) else None
        for name in booleans:
            row[name] = bool(row[name]) if row.get(name) is not None else None
    return pa.Table.from_pylist(rows, schema=schema)


def _offer_schema(pa: Any) -> Any:
    types = {
        "text": pa.string(),
        "time": pa.timestamp("us", tz="UTC"),
        "int": pa.int64(),
        "float": pa.float64(),
        "bool": pa.bool_(),
    }
    fields = (
        ("observation_id", "text"),
        ("batch_id", "text"),
        ("market_run_id", "text"),
        ("observation_purpose", "text"),
        ("observation_resolution", "text"),
        ("selection_resolution", "text"),
        ("observed_at", "time"),
        ("provider", "text"),
        ("source_connector", "text"),
        ("source_offer_id", "text"),
        ("gpu_raw_name", "text"),
        ("gpu_model", "text"),
        ("gpu_count", "int"),
        ("vram_gb", "float"),
        ("price_usd_instance_hr", "float"),
        ("price_usd_gpu_hr", "float"),
        ("currency", "text"),
        ("available_gpu_count_lower_bound", "int"),
        ("is_available", "bool"),
        ("source_availability_status", "text"),
        ("source_stock_status", "text"),
        ("country", "text"),
        ("region", "text"),
        ("cloud_type", "text"),
        ("location_ids_json", "text"),
        ("selection_fingerprint", "text"),
        ("native_selection_json", "text"),
        ("query_scope_json", "text"),
        ("response_complete", "bool"),
        ("is_spot", "bool"),
        ("is_secure", "bool"),
        ("gpu_socket", "text"),
        ("price_is_variable", "bool"),
        ("minimum_executable_price_usd_instance_hr", "float"),
        ("required_resource_price_usd_instance_hr", "float"),
        ("price_basis", "text"),
        ("raw_ref", "text"),
        ("raw_hash", "text"),
        ("source_run_id", "text"),
        ("source_manifest_ref", "text"),
        ("source_normalized_ref", "text"),
        ("methodology_version", "text"),
        ("schema_version", "text"),
    )
    return pa.schema([(name, types[kind]) for name, kind in fields])


def _allocation_schema(pa: Any) -> Any:
    return pa.schema(
        [
            ("host_id", pa.string()),
            ("provider", pa.string()),
            ("provider_resource_id", pa.string()),
            ("offer_observation_id", pa.string()),
            ("offer_batch_id", pa.string()),
            ("offer_id", pa.string()),
            ("plan_id", pa.string()),
            ("name", pa.string()),
            ("cloud_type", pa.string()),
            ("location", pa.string()),
            ("state", pa.string()),
            ("gpu_family", pa.string()),
            ("gpu_model", pa.string()),
            ("gpu_count", pa.int64()),
            ("selected_price_usd_gpu_hr", pa.float64()),
            ("selected_price_usd_instance_hr", pa.float64()),
            ("offer_observed_at", pa.timestamp("us", tz="UTC")),
            ("launched_at", pa.timestamp("us", tz="UTC")),
            ("terminate_at", pa.timestamp("us", tz="UTC")),
            ("terminated_at", pa.timestamp("us", tz="UTC")),
            ("expected_max_cost_usd", pa.float64()),
            ("ssh_ready", pa.bool_()),
            ("updated_at", pa.timestamp("us", tz="UTC")),
        ]
    )


def _fleet_observation_schema(pa: Any) -> Any:
    return pa.schema(
        [
            ("observation_id", pa.string()),
            ("host_id", pa.string()),
            ("provider", pa.string()),
            ("observed_at", pa.timestamp("us", tz="UTC")),
            ("readiness", pa.string()),
            ("gpu_count_detected", pa.int64()),
            ("gpu_utilization_pct", pa.float64()),
            ("gpu_memory_used_mb", pa.int64()),
            ("gpu_memory_total_mb", pa.int64()),
            ("gpu_temperature_c", pa.int64()),
            ("cpu_utilization_pct", pa.float64()),
            ("memory_used_mb", pa.int64()),
            ("memory_mb", pa.int64()),
            ("disk_free_gb", pa.int64()),
            ("driver_versions", pa.string()),
            ("driver_cuda_version", pa.string()),
            ("cuda_toolkit_version", pa.string()),
            ("inspection_json", pa.string()),
            ("checks_json", pa.string()),
        ]
    )


def _machine_schema(pa: Any) -> Any:
    return pa.schema(
        [
            ("host_id", pa.string()),
            ("provider", pa.string()),
            ("provider_resource_id", pa.string()),
            ("name", pa.string()),
            ("state", pa.string()),
            ("gpu_model", pa.string()),
            ("gpu_count", pa.int64()),
            ("price_usd_gpu_hr", pa.float64()),
            ("price_usd_instance_hr", pa.float64()),
            ("created_at", pa.timestamp("us", tz="UTC")),
            ("terminate_at", pa.timestamp("us", tz="UTC")),
            ("ssh_ready", pa.bool_()),
            ("ssh_host", pa.string()),
            ("ssh_port", pa.int64()),
            ("ssh_user", pa.string()),
        ]
    )


def _machine_row(machine: FleetMachine) -> dict[str, Any]:
    return {
        "host_id": machine.host_id,
        "provider": machine.provider,
        "provider_resource_id": machine.provider_resource_id,
        "name": machine.name,
        "state": machine.state,
        "gpu_model": machine.gpu_model,
        "gpu_count": machine.gpu_count,
        "price_usd_gpu_hr": machine.price_usd_gpu_hr,
        "price_usd_instance_hr": machine.price_usd_instance_hr,
        "created_at": machine.created_at,
        "terminate_at": machine.terminate_at,
        "ssh_ready": machine.ssh is not None,
        "ssh_host": machine.ssh.host if machine.ssh else None,
        "ssh_port": machine.ssh.port if machine.ssh else None,
        "ssh_user": machine.ssh.user if machine.ssh else None,
    }


def _gpu_family(model: str) -> str | None:
    upper = model.upper()
    return next(
        (
            family
            for family in ("H100", "H200", "B200", "B300", "A100")
            if upper == family or upper.startswith(f"{family}_")
        ),
        None,
    )


def _sqlite(value: Any) -> Any:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, datetime):
        return _timestamp(value)
    return value


def _mtime(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except FileNotFoundError:
        return 0


def _identity(*parts: str) -> str:
    import hashlib

    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:24]


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _average(values: Any) -> float | None:
    present = [float(value) for value in values if value is not None]
    return sum(present) / len(present) if present else None
