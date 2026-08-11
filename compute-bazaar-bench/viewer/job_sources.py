"""Discover Harbor jobs and optional post-run analysis."""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path
from typing import Any


TRANSACTIONS_SCHEMA = "compute-bazaar-bench.transactions.analysis.v1"
TRANSACTIONS_COMPARISON_SCHEMA = (
    "compute-bazaar-bench.transactions.comparison-analysis.v1"
)
TRANSACTIONS_ADJUDICATION_SCHEMA = (
    "compute-bazaar-bench.transactions.adjudication-analysis.v1"
)
TRANSACTIONS_RELEASE_SUMMARY_SCHEMA = (
    "compute-bazaar-bench.transactions.release-summary.v1"
)
PUBLIC_VIEW_SCHEMA = "compute-bazaar-bench.public-view.v1"
PUBLIC_VIEW_PATH = Path("evals/transactions/tooling/public-view.json")


@dataclass(frozen=True)
class JobSource:
    """Files available for one task within one Harbor job."""

    task_slug: str
    job_id: str
    raw_dir: Path | None = None
    report_dir: Path | None = None
    notes_dir: Path | None = None
    public_context: dict[str, Any] | None = None

    @property
    def modified_at(self) -> float:
        candidates = []
        for root in (self.raw_dir, self.report_dir):
            if root is None:
                continue
            for name in ("result.json", "analysis.json", "view.json", "protocol.json"):
                path = root / name
                if path.is_file():
                    candidates.append(path.stat().st_mtime)
        return max(candidates, default=0.0)


def discover_job_sources(
    bench_root: Path, reports_root: Path
) -> dict[str, dict[str, JobSource]]:
    """Join raw Harbor jobs with optional reports, keyed by task and job."""
    reports_root = reports_root.resolve()
    jobs_root = bench_root / "jobs"
    discovered: dict[str, dict[str, JobSource]] = {}
    raw_jobs = _discover_raw_jobs(jobs_root)

    for task_slug, jobs in raw_jobs.items():
        for job_id, raw_dir in jobs.items():
            note_dir = reports_root / task_slug / "jobs" / job_id
            discovered.setdefault(task_slug, {})[job_id] = JobSource(
                task_slug=task_slug,
                job_id=job_id,
                raw_dir=raw_dir,
                notes_dir=note_dir,
            )

    for task_slug, jobs in _discover_reports(reports_root).items():
        for job_id, report_dir in jobs.items():
            existing = discovered.setdefault(task_slug, {}).get(job_id)
            note_dir = report_dir
            if existing is None:
                discovered[task_slug][job_id] = JobSource(
                    task_slug=task_slug,
                    job_id=job_id,
                    report_dir=report_dir,
                    notes_dir=note_dir,
                )
            else:
                discovered[task_slug][job_id] = replace(
                    existing,
                    report_dir=report_dir,
                    notes_dir=note_dir,
                )

    comparison_reports = _comparison_job_reports(reports_root)
    for task_slug, jobs in raw_jobs.items():
        for job_id in jobs:
            report_dir = comparison_reports.get(job_id)
            if report_dir is None:
                continue
            existing = discovered[task_slug][job_id]
            discovered[task_slug][job_id] = replace(
                existing,
                report_dir=report_dir,
            )
    return _apply_public_view(discovered, bench_root)


def load_public_release_summary(
    bench_root: Path, reports_root: Path
) -> dict[str, Any] | None:
    """Load the optional aggregate table bound by the public release manifest."""
    view_path = bench_root / PUBLIC_VIEW_PATH
    if not view_path.is_file():
        return None
    view = _read_json(view_path)
    if not isinstance(view, dict) or view.get("schema_version") != PUBLIC_VIEW_SCHEMA:
        raise RuntimeError(f"invalid public view manifest: {view_path}")
    configured_path = view.get("summary_path")
    if isinstance(configured_path, str) and configured_path:
        summary_path = (bench_root / configured_path).resolve()
        try:
            summary_path.relative_to(bench_root.resolve())
        except ValueError as exc:
            raise RuntimeError("public release summary escapes benchmark root") from exc
    else:
        report_name = view.get("report")
        if not isinstance(report_name, str) or not report_name:
            return None
        summary_path = reports_root.resolve() / report_name / "summary.json"
    if not summary_path.is_file():
        return None
    summary = _read_json(summary_path)
    if (
        not isinstance(summary, dict)
        or summary.get("schema_version") != TRANSACTIONS_RELEASE_SUMMARY_SCHEMA
    ):
        raise RuntimeError(f"invalid public release summary: {summary_path}")
    if summary.get("release_id") != view.get("release_id"):
        raise RuntimeError("public release summary ID does not match public view")
    if summary.get("protocol_sha256") != view.get("protocol_sha256"):
        raise RuntimeError("public release summary protocol does not match public view")
    managed = view.get("managed_tasks")
    if not isinstance(managed, list):
        raise RuntimeError("public view has no managed task list")
    return {"managed_tasks": managed, "summary": summary}


def _apply_public_view(
    discovered: dict[str, dict[str, JobSource]], bench_root: Path
) -> dict[str, dict[str, JobSource]]:
    """Hide private calibration jobs for tasks governed by a public release."""
    path = bench_root / PUBLIC_VIEW_PATH
    if not path.is_file():
        return discovered
    view = _read_json(path)
    if not isinstance(view, dict) or view.get("schema_version") != PUBLIC_VIEW_SCHEMA:
        raise RuntimeError(f"invalid public view manifest: {path}")
    managed = view.get("managed_tasks")
    allowed = view.get("jobs")
    if not isinstance(managed, list) or not all(
        isinstance(item, str) and item for item in managed
    ):
        raise RuntimeError(f"invalid managed task list: {path}")
    if not isinstance(allowed, list) or not all(
        isinstance(item, str) and item for item in allowed
    ):
        raise RuntimeError(f"invalid public job list: {path}")
    metadata = view.get("job_metadata", {})
    if not isinstance(metadata, dict) or not all(
        isinstance(job_id, str) and isinstance(value, dict)
        for job_id, value in metadata.items()
    ):
        raise RuntimeError(f"invalid public job metadata: {path}")
    allowed_jobs = set(allowed)
    if set(metadata) != allowed_jobs:
        raise RuntimeError(f"public job metadata does not match job list: {path}")
    release_id = view.get("release_id")
    if not isinstance(release_id, str) or not release_id:
        raise RuntimeError(f"invalid public release ID: {path}")
    private_release_prefix = f"{release_id}-"
    for task_slug in managed:
        if task_slug not in discovered:
            continue
        discovered[task_slug] = {
            job_id: replace(
                source,
                public_context={
                    "release_id": view.get("release_id"),
                    **metadata[job_id],
                },
            )
            for job_id, source in discovered[task_slug].items()
            if job_id in allowed_jobs
        }
    for task_slug, jobs in discovered.items():
        if task_slug in managed:
            continue
        discovered[task_slug] = {
            job_id: source
            for job_id, source in jobs.items()
            if not (
                job_id.startswith(private_release_prefix) and job_id not in allowed_jobs
            )
        }
    discovered = {task: jobs for task, jobs in discovered.items() if jobs}
    return discovered


def _discover_raw_jobs(jobs_root: Path) -> dict[str, dict[str, Path]]:
    """Discover canonical jobs plus the legacy jobs/raw layout."""
    output: dict[str, dict[str, Path]] = {}
    roots = (jobs_root, jobs_root / "raw")
    for root in roots:
        if not root.is_dir():
            continue
        for job_dir in sorted(path for path in root.iterdir() if path.is_dir()):
            if root == jobs_root and job_dir.name in {
                "adjudications",
                "raw",
                "reports",
            }:
                continue
            if not any(
                (job_dir / name).is_file()
                for name in ("lock.json", "result.json", "config.json")
            ):
                continue
            for task_slug in _raw_job_tasks(job_dir):
                output.setdefault(task_slug, {}).setdefault(job_dir.name, job_dir)
    return output


def _raw_job_tasks(job_dir: Path) -> set[str]:
    names: set[str] = set()
    for result_path in job_dir.glob("*/result.json"):
        result = _read_json(result_path)
        if isinstance(result, dict) and result.get("task_name"):
            names.add(_slug(result["task_name"]))
    if names and names != {"task"}:
        return names
    names.clear()
    lock = _read_json(job_dir / "lock.json")
    if isinstance(lock, dict):
        for trial in lock.get("trials", []):
            if not isinstance(trial, dict):
                continue
            task = trial.get("task")
            if isinstance(task, dict) and task.get("name"):
                names.add(_task_slug(task))
    if names:
        return names
    return names


def _discover_reports(reports_root: Path) -> dict[str, dict[str, Path]]:
    output: dict[str, dict[str, Path]] = {}
    if not reports_root.is_dir():
        return output

    for report_dir in sorted(path for path in reports_root.iterdir() if path.is_dir()):
        analysis = _read_json(report_dir / "analysis.json")
        if (
            isinstance(analysis, dict)
            and analysis.get("schema_version") == TRANSACTIONS_SCHEMA
        ):
            job_id = str(analysis.get("job") or report_dir.name)
            tasks = analysis.get("summary", {}).get("tasks", {})
            if isinstance(tasks, dict):
                for task_name in tasks:
                    output.setdefault(_slug(task_name), {})[job_id] = report_dir
        if (
            isinstance(analysis, dict)
            and analysis.get("schema_version") == TRANSACTIONS_COMPARISON_SCHEMA
        ):
            for model_run in (analysis.get("models") or {}).values():
                if not isinstance(model_run, dict) or not model_run.get("job"):
                    continue
                job_id = str(model_run["job"])
                tasks = (model_run.get("summary") or {}).get("tasks") or {}
                if isinstance(tasks, dict):
                    for task_name in tasks:
                        output.setdefault(_slug(task_name), {})[job_id] = report_dir
        if (
            isinstance(analysis, dict)
            and analysis.get("schema_version") == TRANSACTIONS_ADJUDICATION_SCHEMA
        ):
            for model_run in (analysis.get("models") or {}).values():
                if not isinstance(model_run, dict) or not model_run.get("job"):
                    continue
                job_id = str(model_run["job"])
                tasks = (model_run.get("amended") or {}).get("tasks") or {}
                if isinstance(tasks, dict):
                    for task_name in tasks:
                        output.setdefault(_slug(task_name), {})[job_id] = report_dir

    for container in ("runs", "jobs"):
        for report_dir in sorted(reports_root.glob(f"*/{container}/*")):
            if not report_dir.is_dir():
                continue
            if not _is_report(report_dir):
                continue
            task_slug = report_dir.parent.parent.name
            output.setdefault(task_slug, {})[report_dir.name] = report_dir
    return output


def _comparison_job_reports(reports_root: Path) -> dict[str, Path]:
    output: dict[str, Path] = {}
    if not reports_root.is_dir():
        return output
    for report_dir in sorted(path for path in reports_root.iterdir() if path.is_dir()):
        analysis = _read_json(report_dir / "analysis.json")
        if not isinstance(analysis, dict):
            continue
        if analysis.get("schema_version") not in {
            TRANSACTIONS_COMPARISON_SCHEMA,
            TRANSACTIONS_ADJUDICATION_SCHEMA,
        }:
            continue
        for model_run in (analysis.get("models") or {}).values():
            if isinstance(model_run, dict) and model_run.get("job"):
                output[str(model_run["job"])] = report_dir
    return output


def _is_report(path: Path) -> bool:
    return (path / "view.json").is_file() or (
        (path / "protocol.json").is_file() and (path / "trials.json").is_file()
    )


def _slug(value: Any) -> str:
    return str(value).rsplit("/", 1)[-1]


def _task_slug(task: dict[str, Any]) -> str:
    name = _slug(task.get("name"))
    path = task.get("path")
    if name == "task" and isinstance(path, str):
        package = Path(path)
        if package.name == "task" and package.parent.name:
            return package.parent.name
    return name


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
