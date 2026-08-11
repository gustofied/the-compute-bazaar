"""Background polling for active Fleet machines."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Event, Lock, Thread

from .models import FleetDoctorResult, FleetInspection, FleetMachine
from .service import FleetService


@dataclass(frozen=True)
class FleetMonitorState:
    inspection: FleetInspection | None
    doctor: FleetDoctorResult | None
    polled_at: datetime
    error: str | None = None
    consecutive_failures: int = 0

    @property
    def status(self) -> str:
        if self.inspection is None:
            return "fault" if self.error else "waiting"
        return "stale" if self.error else "ok"


class FleetMonitor:
    def __init__(self, service: FleetService, *, interval_seconds: float = 5) -> None:
        self.service = service
        self.interval_seconds = max(1.0, interval_seconds)
        self._states: dict[str, FleetMonitorState] = {}
        self._lock = Lock()
        self._stop = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = Thread(target=self._run, name="fleet-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=max(2.0, self.interval_seconds + 1))
        self._thread = None

    def state(self, host_id: str) -> FleetMonitorState | None:
        with self._lock:
            return self._states.get(host_id)

    def states(self) -> dict[str, FleetMonitorState]:
        with self._lock:
            return dict(self._states)

    def poll_once(self) -> None:
        hosts = [machine for machine in self.service.hosts() if _pollable(machine)]
        if not hosts:
            return
        workers = min(8, len(hosts))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(self.service.monitor, machine.host_id): machine.host_id
                for machine in hosts
            }
            for future in as_completed(futures):
                host_id = futures[future]
                try:
                    inspection, doctor = future.result()
                except (
                    Exception
                ) as exc:  # One failed host must not stop the fleet loop.
                    self._record_failure(host_id, str(exc))
                else:
                    self._record_success(host_id, inspection, doctor)

    def _run(self) -> None:
        while not self._stop.is_set():
            self.poll_once()
            self._stop.wait(self.interval_seconds)

    def _record_success(
        self,
        host_id: str,
        inspection: FleetInspection,
        doctor: FleetDoctorResult,
    ) -> None:
        with self._lock:
            self._states[host_id] = FleetMonitorState(
                inspection=inspection,
                doctor=doctor,
                polled_at=datetime.now(UTC),
            )

    def _record_failure(self, host_id: str, error: str) -> None:
        with self._lock:
            previous = self._states.get(host_id)
            self._states[host_id] = FleetMonitorState(
                inspection=previous.inspection if previous else None,
                doctor=previous.doctor if previous else None,
                polled_at=datetime.now(UTC),
                error=error,
                consecutive_failures=(previous.consecutive_failures if previous else 0)
                + 1,
            )


def _pollable(machine: FleetMachine) -> bool:
    return machine.state == "running" and machine.ssh is not None
