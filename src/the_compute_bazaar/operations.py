"""Private evidence, provisioning, allocation, and Fleet history."""

from __future__ import annotations

import fcntl
import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from .fleet.registry import FleetRegistry, default_fleet_root

if TYPE_CHECKING:
    import pyarrow as pa

    from .fleet.models import FleetDoctorResult, FleetInspection, FleetMachine
    from .fleet.workloads import WorkloadRun
    from .offers import OfferBatch
    from .provisioning import Allocation, ProvisioningAttempt, ProvisioningRequest


SCHEMA_VERSION = 5
TELEMETRY_RETENTION = timedelta(hours=6)

ALLOCATIONS_SCHEMA = """
create table if not exists allocations (
  allocation_id text primary key,
  request_id text not null unique,
  successful_attempt_id text not null unique,
  acquisition_connector text not null,
  capacity_provider text not null,
  provider_resource_id text not null,
  state text not null,
  realized_price_usd_gpu_hr real,
  realized_price_usd_instance_hr real,
  created_at text not null,
  terminate_at text,
  terminated_at text,
  updated_at text not null,
  foreign key (request_id) references provisioning_requests(request_id),
  foreign key (successful_attempt_id) references provisioning_attempts(attempt_id)
);
"""

SCHEMA = f"""
create table if not exists provider_read_batches (
  batch_id text not null,
  source_connector text not null,
  observed_at text not null,
  purpose text not null,
  query_scope_json text not null,
  raw_ref text not null,
  raw_hash text not null,
  sanitized_payload_json text not null,
  primary key (batch_id, source_connector)
);

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
  market_product_key text,
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

create index if not exists offer_observations_offer_time
  on offer_observations (source_offer_id, observed_at desc);

create table if not exists provisioning_requests (
  request_id text primary key,
  plan_id text not null,
  candidate_observation_id text,
  preflight_observation_id text not null,
  preflight_batch_id text not null,
  source_offer_id text not null,
  market_product_key text not null,
  acquisition_connector text not null,
  capacity_provider text not null,
  operation text not null,
  gpu_model text not null,
  gpu_count integer not null,
  selected_price_usd_gpu_hr real not null,
  selected_price_usd_instance_hr real not null,
  max_hourly_usd real not null,
  runtime_minutes integer not null,
  expected_max_cost_usd real not null,
  request_hash text not null,
  provider_request_json text not null,
  created_at text not null,
  state text not null,
  foreign key (candidate_observation_id) references offer_observations(observation_id),
  foreign key (preflight_observation_id) references offer_observations(observation_id)
);

create table if not exists provisioning_attempts (
  attempt_id text primary key,
  request_id text not null,
  attempt_number integer not null,
  state text not null,
  started_at text not null,
  completed_at text,
  provider_resource_id text,
  error text,
  unique (request_id, attempt_number),
  foreign key (request_id) references provisioning_requests(request_id)
);

{ALLOCATIONS_SCHEMA}

create table if not exists fleet_telemetry (
  sample_id text primary key,
  host_id text not null,
  observed_at text not null,
  gpu_count_detected integer not null,
  gpu_utilization_pct real,
  gpu_memory_used_mb integer,
  gpu_memory_total_mb integer,
  gpu_temperature_c integer,
  gpu_power_draw_w real,
  cpu_utilization_pct real,
  memory_used_mb integer,
  memory_mb integer,
  disk_free_gb integer,
  error text
);

create index if not exists fleet_telemetry_host_time
  on fleet_telemetry (host_id, observed_at desc);

create table if not exists capacity_verifications (
  verification_id text primary key,
  host_id text not null,
  observed_at text not null,
  readiness text not null,
  expected_gpu_count integer not null,
  detected_gpu_count integer not null,
  inspection_json text not null,
  checks_json text not null
);

create index if not exists capacity_verifications_host_time
  on capacity_verifications (host_id, observed_at desc);

create table if not exists workload_runs (
  workload_id text primary key,
  host_id text not null,
  allocation_id text,
  name text not null,
  command_json text not null,
  working_directory text not null,
  remote_directory text not null,
  state text not null,
  remote_pid integer,
  exit_code integer,
  started_at text not null,
  ended_at text,
  updated_at text not null,
  stdout_ref text not null,
  stderr_ref text not null,
  error text
);

create index if not exists workload_runs_host_time
  on workload_runs (host_id, started_at desc);
"""


class ProvisioningStateError(RuntimeError):
    """A request cannot safely move to another provider call."""


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

    def record_offer_batch(self, batch: OfferBatch) -> None:
        evidence = [
            {
                "batch_id": item.batch_id,
                "source_connector": item.source_connector,
                "observed_at": item.observed_at,
                "purpose": item.purpose,
                "query_scope_json": _json(item.query_scope),
                "raw_ref": item.raw_ref,
                "raw_hash": item.raw_hash,
                "sanitized_payload_json": _json(item.sanitized_payload),
            }
            for item in batch.provider_reads
        ]
        observations = [item.row() for item in batch.observations]
        if any(not row["observation_id"] for row in observations):
            raise ValueError("Direct offer observation has no observation_id")
        with closing(self._connect()) as connection, connection:
            _insert(connection, "provider_read_batches", evidence, ignore=True)
            _insert(connection, "offer_observations", observations, ignore=True)

    def latest_offer_observation_id(self, source_offer_id: str) -> str | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
select observation_id
from offer_observations
where source_offer_id = ?
  and observation_purpose = 'interactive'
order by observed_at desc, observation_id desc
limit 1
""",
                (source_offer_id,),
            ).fetchone()
        return str(row["observation_id"]) if row else None

    def begin_provisioning(
        self, request: ProvisioningRequest
    ) -> ProvisioningAttempt:
        from .provisioning import ProvisioningAttempt

        with closing(self._connect()) as connection:
            connection.execute("begin immediate")
            try:
                existing = connection.execute(
                    "select request_hash from provisioning_requests where request_id = ?",
                    (request.request_id,),
                ).fetchone()
                if existing and existing["request_hash"] != request.request_hash:
                    raise ProvisioningStateError(
                        f"Provisioning request identity collision: {request.request_id}"
                    )
                if not existing:
                    _insert(
                        connection,
                        "provisioning_requests",
                        [_request_row(request)],
                    )
                latest = connection.execute(
                    """
select attempt_number, state
from provisioning_attempts
where request_id = ?
order by attempt_number desc
limit 1
""",
                    (request.request_id,),
                ).fetchone()
                if latest and latest["state"] in {"pending", "uncertain", "succeeded"}:
                    raise ProvisioningStateError(
                        f"Provisioning request {request.request_id} is "
                        f"{latest['state']}; reconcile it before retrying"
                    )
                number = int(latest["attempt_number"]) + 1 if latest else 1
                attempt = ProvisioningAttempt(
                    attempt_id=f"attempt-{_identity(request.request_id, str(number))}",
                    request_id=request.request_id,
                    attempt_number=number,
                    state="pending",
                    started_at=datetime.now(UTC),
                )
                _insert(
                    connection,
                    "provisioning_attempts",
                    [attempt.model_dump(mode="python")],
                )
                connection.execute(
                    "update provisioning_requests set state = 'pending' where request_id = ?",
                    (request.request_id,),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return attempt

    def complete_provisioning_attempt(
        self,
        attempt_id: str,
        *,
        state: Literal["succeeded", "failed", "uncertain"],
        provider_resource_id: str | None = None,
        error: str | None = None,
        completed_at: datetime | None = None,
    ) -> None:
        completed_at = completed_at or datetime.now(UTC)
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "select request_id, state from provisioning_attempts where attempt_id = ?",
                (attempt_id,),
            ).fetchone()
            if not row:
                raise KeyError(f"Unknown provisioning attempt: {attempt_id}")
            if row["state"] != "pending":
                raise ProvisioningStateError(
                    f"Provisioning attempt {attempt_id} is already {row['state']}"
                )
            connection.execute(
                """
update provisioning_attempts
set state = ?, completed_at = ?, provider_resource_id = ?, error = ?
where attempt_id = ?
""",
                (
                    state,
                    _timestamp(completed_at),
                    provider_resource_id,
                    error,
                    attempt_id,
                ),
            )
            connection.execute(
                "update provisioning_requests set state = ? where request_id = ?",
                (state, row["request_id"]),
            )

    def reconcile_attempt(
        self,
        attempt_id: str,
        *,
        state: Literal["succeeded", "failed"],
        provider_resource_id: str | None = None,
        note: str | None = None,
    ) -> None:
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "select request_id, state from provisioning_attempts where attempt_id = ?",
                (attempt_id,),
            ).fetchone()
            if not row:
                raise KeyError(f"Unknown provisioning attempt: {attempt_id}")
            if row["state"] != "uncertain":
                raise ProvisioningStateError(
                    f"Only an uncertain attempt can be reconciled; found {row['state']}"
                )
            connection.execute(
                """
update provisioning_attempts
set state = ?, completed_at = ?, provider_resource_id = coalesce(?, provider_resource_id),
    error = ?
where attempt_id = ?
""",
                (
                    state,
                    _timestamp(datetime.now(UTC)),
                    provider_resource_id,
                    note,
                    attempt_id,
                ),
            )
            connection.execute(
                "update provisioning_requests set state = ? where request_id = ?",
                (state, row["request_id"]),
            )

    def provisioning_attempt(self, attempt_id: str) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
select
  attempt.attempt_id,
  attempt.attempt_number,
  attempt.state as attempt_state,
  attempt.started_at,
  attempt.completed_at,
  attempt.provider_resource_id,
  attempt.error,
  request.*
from provisioning_attempts attempt
join provisioning_requests request using (request_id)
where attempt.attempt_id = ?
""",
                (attempt_id,),
            ).fetchone()
        if not row:
            raise KeyError(f"Unknown provisioning attempt: {attempt_id}")
        return dict(row)

    def allocation_for_request(self, request_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "select * from allocations where request_id = ?",
                (request_id,),
            ).fetchone()
        return dict(row) if row else None

    def complete_allocation(
        self,
        attempt_id: str,
        allocation: Allocation,
        *,
        recover: bool = False,
        note: str | None = None,
    ) -> None:
        with closing(self._connect()) as connection, connection:
            attempt = connection.execute(
                """
select request_id, state, provider_resource_id
from provisioning_attempts
where attempt_id = ?
""",
                (attempt_id,),
            ).fetchone()
            if not attempt:
                raise ProvisioningStateError(f"Unknown provisioning attempt: {attempt_id}")
            allowed = {"uncertain", "succeeded"} if recover else {"pending"}
            if attempt["state"] not in allowed:
                raise ProvisioningStateError(
                    f"Provisioning attempt {attempt_id} is {attempt['state']}"
                )
            if attempt["request_id"] != allocation.request_id:
                raise ProvisioningStateError(
                    "Allocation request does not match its provisioning attempt"
                )
            provider_resource_id = attempt["provider_resource_id"]
            if provider_resource_id and provider_resource_id != allocation.provider_resource_id:
                raise ProvisioningStateError(
                    "Allocation resource does not match its provisioning attempt"
                )
            existing = connection.execute(
                "select allocation_id from allocations where request_id = ?",
                (allocation.request_id,),
            ).fetchone()
            if existing:
                if existing["allocation_id"] == allocation.allocation_id:
                    return
                raise ProvisioningStateError(
                    f"Request {allocation.request_id} already has an allocation"
                )
            now = _timestamp(datetime.now(UTC))
            connection.execute(
                """
update provisioning_attempts
set state = 'succeeded', completed_at = ?, provider_resource_id = ?, error = ?
where attempt_id = ?
""",
                (now, allocation.provider_resource_id, note, attempt_id),
            )
            connection.execute(
                "update provisioning_requests set state = 'succeeded' where request_id = ?",
                (allocation.request_id,),
            )
            _insert(
                connection,
                "allocations",
                [allocation.model_dump(mode="python")],
            )

    def allocation_for_machine(self, machine: FleetMachine) -> dict[str, Any]:
        if not machine.allocation_id:
            raise KeyError(f"Fleet node {machine.host_id} has no allocation")
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
select
  allocation.*,
  request.gpu_model,
  request.gpu_count,
  request.selected_price_usd_gpu_hr,
  request.selected_price_usd_instance_hr,
  request.expected_max_cost_usd
from allocations allocation
join provisioning_requests request using (request_id)
where allocation_id = ?
""",
                (machine.allocation_id,),
            ).fetchone()
        if not row:
            raise KeyError(f"Unknown allocation: {machine.allocation_id}")
        return dict(row)

    def record_machine_state(
        self,
        machine: FleetMachine,
        *,
        occurred_at: datetime | None = None,
    ) -> None:
        if not machine.allocation_id:
            return
        when = occurred_at or datetime.now(UTC)
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
update allocations
set state = ?,
    terminated_at = case when ? = 'terminated' then ? else terminated_at end,
    updated_at = ?
where allocation_id = ?
""",
                (
                    machine.state,
                    machine.state,
                    _timestamp(when),
                    _timestamp(when),
                    machine.allocation_id,
                ),
            )

    def record_telemetry(
        self,
        inspection: FleetInspection,
        *,
        error: str | None = None,
    ) -> None:
        gpus = inspection.gpus
        row = {
            "sample_id": _identity(
                inspection.machine.host_id, inspection.observed_at.isoformat()
            ),
            "host_id": inspection.machine.host_id,
            "observed_at": inspection.observed_at,
            "gpu_count_detected": len(gpus),
            "gpu_utilization_pct": _average(gpu.utilization_pct for gpu in gpus),
            "gpu_memory_used_mb": sum(gpu.memory_used_mb for gpu in gpus) if gpus else None,
            "gpu_memory_total_mb": sum(gpu.memory_total_mb for gpu in gpus) if gpus else None,
            "gpu_temperature_c": max(
                (gpu.temperature_c for gpu in gpus if gpu.temperature_c is not None),
                default=None,
            ),
            "gpu_power_draw_w": sum(
                gpu.power_draw_w for gpu in gpus if gpu.power_draw_w is not None
            )
            if any(gpu.power_draw_w is not None for gpu in gpus)
            else None,
            "cpu_utilization_pct": inspection.cpu_utilization_pct,
            "memory_used_mb": inspection.memory_used_mb,
            "memory_mb": inspection.memory_mb,
            "disk_free_gb": inspection.disk_free_gb,
            "error": error,
        }
        cutoff = inspection.observed_at - TELEMETRY_RETENTION
        with closing(self._connect()) as connection, connection:
            _insert(connection, "fleet_telemetry", [row], replace=True)
            connection.execute(
                "delete from fleet_telemetry where observed_at < ?",
                (_timestamp(cutoff),),
            )

    def record_capacity_verification(
        self,
        inspection: FleetInspection,
        doctor: FleetDoctorResult,
    ) -> None:
        row = {
            "verification_id": f"verify-{_identity(doctor.host_id, doctor.observed_at.isoformat())}",
            "host_id": doctor.host_id,
            "observed_at": doctor.observed_at,
            "readiness": doctor.readiness,
            "expected_gpu_count": inspection.machine.gpu_count,
            "detected_gpu_count": len(inspection.gpus),
            "inspection_json": _json(inspection.model_dump(mode="json")),
            "checks_json": _json(doctor.payload()),
        }
        self._insert("capacity_verifications", [row], replace=True)

    def latest_capacity_verification(self, host_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
select * from capacity_verifications
where host_id = ?
order by observed_at desc
limit 1
""",
                (host_id,),
            ).fetchone()
        return dict(row) if row else None

    def record_workload(self, workload: WorkloadRun) -> None:
        self._insert("workload_runs", [_workload_row(workload)])

    def update_workload(self, workload: WorkloadRun) -> None:
        self._insert("workload_runs", [_workload_row(workload)], replace=True)

    def workload(self, workload_id: str) -> WorkloadRun:
        from .fleet.workloads import WorkloadRun

        with closing(self._connect()) as connection:
            row = connection.execute(
                "select * from workload_runs where workload_id = ?",
                (workload_id,),
            ).fetchone()
        if not row:
            raise KeyError(f"Unknown Fleet workload: {workload_id}")
        return WorkloadRun.model_validate(_workload_payload(dict(row)))

    def workloads(self, host_id: str | None = None) -> list[WorkloadRun]:
        from .fleet.workloads import WorkloadRun

        sql = "select * from workload_runs"
        values: tuple[str, ...] = ()
        if host_id:
            sql += " where host_id = ?"
            values = (host_id,)
        sql += " order by started_at desc, workload_id desc"
        with closing(self._connect()) as connection:
            rows = connection.execute(sql, values).fetchall()
        return [
            WorkloadRun.model_validate(_workload_payload(dict(row))) for row in rows
        ]

    def stop_host_workloads(
        self,
        host_id: str,
        *,
        reason: str,
        ended_at: datetime | None = None,
    ) -> int:
        when = _timestamp(ended_at or datetime.now(UTC))
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                """
update workload_runs
set state = 'stopped', ended_at = ?, updated_at = ?, error = ?
where host_id = ? and state in ('starting', 'running', 'unknown')
""",
                (when, when, reason, host_id),
            )
        return cursor.rowcount

    def arrow_tables(self) -> dict[str, pa.Table]:
        import pyarrow as pa

        schemas = {
            "provider_read_batches": _provider_read_schema(pa),
            "offer_observations": _offer_schema(pa),
            "provisioning_requests": _request_schema(pa),
            "provisioning_attempts": _attempt_schema(pa),
            "allocations": _allocation_schema(pa),
            "fleet_telemetry": _telemetry_schema(pa),
            "capacity_verifications": _verification_schema(pa),
            "workload_runs": _workload_schema(pa),
        }
        with closing(self._connect()) as connection:
            tables = {
                name: _arrow_table(connection, f"select * from {name}", schema)
                for name, schema in schemas.items()
            }
        tables["fleet_nodes"] = pa.Table.from_pylist(
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
        with closing(self._connect()) as connection, connection:
            _insert(connection, table, rows, ignore=ignore, replace=replace)

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path.parent.chmod(0o700)
        with _schema_lock(self.path):
            connection = sqlite3.connect(self.path, timeout=5)
            try:
                connection.row_factory = sqlite3.Row
                connection.execute("pragma busy_timeout=5000")
                connection.execute("pragma foreign_keys=on")
                connection.execute("pragma journal_mode=wal")
                connection.executescript(SCHEMA)
                connection.execute("begin immediate")
                _migrate(connection)
                connection.execute(
                    "create index if not exists offer_observations_product_time "
                    "on offer_observations (market_product_key, observed_at desc)"
                )
                connection.execute(f"pragma user_version={SCHEMA_VERSION}")
                connection.commit()
            except Exception:
                connection.rollback()
                connection.close()
                raise
        self.path.chmod(0o600)
        return connection


def _migrate(connection: sqlite3.Connection) -> None:
    version = int(connection.execute("pragma user_version").fetchone()[0])
    if version >= SCHEMA_VERSION:
        return
    columns = {
        str(row["name"])
        for row in connection.execute("pragma table_info(offer_observations)")
    }
    if "market_product_key" not in columns:
        connection.execute(
            "alter table offer_observations add column market_product_key text"
        )
    allocation_columns = {
        str(row["name"])
        for row in connection.execute("pragma table_info(allocations)")
    }
    if allocation_columns and "request_id" not in allocation_columns:
        connection.execute("drop table allocations")
        connection.executescript(ALLOCATIONS_SCHEMA)
    connection.execute("drop table if exists fleet_allocations")
    connection.execute("drop table if exists fleet_observations")


@contextmanager
def _schema_lock(path: Path) -> Iterator[None]:
    lock_path = path.with_name(f".{path.name}.schema.lock")
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(descriptor, "a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _insert(
    connection: sqlite3.Connection,
    table: str,
    rows: list[dict[str, Any]],
    *,
    ignore: bool = False,
    replace: bool = False,
) -> None:
    if not rows:
        return
    columns = tuple(rows[0])
    mode = "replace" if replace else "ignore" if ignore else "abort"
    sql = (
        f"insert or {mode} into {table} ({', '.join(columns)}) "
        f"values ({', '.join('?' for _ in columns)})"
    )
    values = [tuple(_sqlite(row[column]) for column in columns) for row in rows]
    connection.executemany(sql, values)


def _request_row(request: ProvisioningRequest) -> dict[str, Any]:
    row = request.model_dump(mode="python")
    row["provider_request_json"] = _json(row.pop("provider_request"))
    return row


def _workload_row(workload: WorkloadRun) -> dict[str, Any]:
    row = workload.model_dump(mode="python")
    row["command_json"] = _json(row.pop("command"))
    return row


def _workload_payload(row: dict[str, Any]) -> dict[str, Any]:
    row["command"] = tuple(json.loads(str(row.pop("command_json"))))
    return row


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


def _schema(pa: Any, fields: tuple[tuple[str, str], ...]) -> Any:
    types = {
        "text": pa.string(),
        "time": pa.timestamp("us", tz="UTC"),
        "int": pa.int64(),
        "float": pa.float64(),
        "bool": pa.bool_(),
    }
    return pa.schema([(name, types[kind]) for name, kind in fields])


def _provider_read_schema(pa: Any) -> Any:
    return _schema(
        pa,
        (
            ("batch_id", "text"),
            ("source_connector", "text"),
            ("observed_at", "time"),
            ("purpose", "text"),
            ("query_scope_json", "text"),
            ("raw_ref", "text"),
            ("raw_hash", "text"),
            ("sanitized_payload_json", "text"),
        ),
    )


def _offer_schema(pa: Any) -> Any:
    return _schema(
        pa,
        (
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
            ("market_product_key", "text"),
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
        ),
    )


def _request_schema(pa: Any) -> Any:
    return _schema(
        pa,
        (
            ("request_id", "text"),
            ("plan_id", "text"),
            ("candidate_observation_id", "text"),
            ("preflight_observation_id", "text"),
            ("preflight_batch_id", "text"),
            ("source_offer_id", "text"),
            ("market_product_key", "text"),
            ("acquisition_connector", "text"),
            ("capacity_provider", "text"),
            ("operation", "text"),
            ("gpu_model", "text"),
            ("gpu_count", "int"),
            ("selected_price_usd_gpu_hr", "float"),
            ("selected_price_usd_instance_hr", "float"),
            ("max_hourly_usd", "float"),
            ("runtime_minutes", "int"),
            ("expected_max_cost_usd", "float"),
            ("request_hash", "text"),
            ("provider_request_json", "text"),
            ("created_at", "time"),
            ("state", "text"),
        ),
    )


def _attempt_schema(pa: Any) -> Any:
    return _schema(
        pa,
        (
            ("attempt_id", "text"),
            ("request_id", "text"),
            ("attempt_number", "int"),
            ("state", "text"),
            ("started_at", "time"),
            ("completed_at", "time"),
            ("provider_resource_id", "text"),
            ("error", "text"),
        ),
    )


def _allocation_schema(pa: Any) -> Any:
    return _schema(
        pa,
        (
            ("allocation_id", "text"),
            ("request_id", "text"),
            ("successful_attempt_id", "text"),
            ("acquisition_connector", "text"),
            ("capacity_provider", "text"),
            ("provider_resource_id", "text"),
            ("state", "text"),
            ("realized_price_usd_gpu_hr", "float"),
            ("realized_price_usd_instance_hr", "float"),
            ("created_at", "time"),
            ("terminate_at", "time"),
            ("terminated_at", "time"),
            ("updated_at", "time"),
        ),
    )


def _telemetry_schema(pa: Any) -> Any:
    return _schema(
        pa,
        (
            ("sample_id", "text"),
            ("host_id", "text"),
            ("observed_at", "time"),
            ("gpu_count_detected", "int"),
            ("gpu_utilization_pct", "float"),
            ("gpu_memory_used_mb", "int"),
            ("gpu_memory_total_mb", "int"),
            ("gpu_temperature_c", "int"),
            ("gpu_power_draw_w", "float"),
            ("cpu_utilization_pct", "float"),
            ("memory_used_mb", "int"),
            ("memory_mb", "int"),
            ("disk_free_gb", "int"),
            ("error", "text"),
        ),
    )


def _verification_schema(pa: Any) -> Any:
    return _schema(
        pa,
        (
            ("verification_id", "text"),
            ("host_id", "text"),
            ("observed_at", "time"),
            ("readiness", "text"),
            ("expected_gpu_count", "int"),
            ("detected_gpu_count", "int"),
            ("inspection_json", "text"),
            ("checks_json", "text"),
        ),
    )


def _workload_schema(pa: Any) -> Any:
    return _schema(
        pa,
        (
            ("workload_id", "text"),
            ("host_id", "text"),
            ("allocation_id", "text"),
            ("name", "text"),
            ("command_json", "text"),
            ("working_directory", "text"),
            ("remote_directory", "text"),
            ("state", "text"),
            ("remote_pid", "int"),
            ("exit_code", "int"),
            ("started_at", "time"),
            ("ended_at", "time"),
            ("updated_at", "time"),
            ("stdout_ref", "text"),
            ("stderr_ref", "text"),
            ("error", "text"),
        ),
    )


def _machine_schema(pa: Any) -> Any:
    return _schema(
        pa,
        (
            ("host_id", "text"),
            ("allocation_id", "text"),
            ("name", "text"),
            ("state", "text"),
            ("gpu_model", "text"),
            ("gpu_count", "int"),
            ("created_at", "time"),
            ("ssh_ready", "bool"),
            ("ssh_host", "text"),
            ("ssh_port", "int"),
            ("ssh_user", "text"),
        ),
    )


def _machine_row(machine: FleetMachine) -> dict[str, Any]:
    return {
        "host_id": machine.host_id,
        "allocation_id": machine.allocation_id,
        "name": machine.name,
        "state": machine.state,
        "gpu_model": machine.gpu_model,
        "gpu_count": machine.gpu_count,
        "created_at": machine.created_at,
        "ssh_ready": machine.ssh is not None,
        "ssh_host": machine.ssh.host if machine.ssh else None,
        "ssh_port": machine.ssh.port if machine.ssh else None,
        "ssh_user": machine.ssh.user if machine.ssh else None,
    }


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
