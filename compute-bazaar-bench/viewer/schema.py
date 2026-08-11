"""Typed presentation contract consumed by the evaluation viewer."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


Tone = Literal["neutral", "good", "warn", "bad", "info"]
Alignment = Literal["left", "right"]


class ViewModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TaskLink(ViewModel):
    label: str
    href: str


class LaunchSpec(ViewModel):
    package_path: str
    task_id: str
    default_agent: str = "terminus-2"
    default_environment: str = "modal"
    default_jobs_dir: str = "compute-bazaar-bench/jobs"
    default_env_file: str = ".env"
    modal_vm_runtime: bool = True


class GraderInfo(ViewModel):
    kind: str
    primary_reward: str
    incomplete_outcome: str
    metrics: str
    integrity: str


class TaskInfo(ViewModel):
    slug: str
    name: str
    domain: str
    description: str = ""
    instruction: str = ""
    grader: GraderInfo | None = None
    links: list[TaskLink] = Field(default_factory=list)
    launch: LaunchSpec | None = None


class Metric(ViewModel):
    label: str
    value: str
    hint: str = ""
    tone: Tone = "neutral"


class BenchmarkLegendItem(ViewModel):
    label: str
    tone: Tone


class BenchmarkSegment(ViewModel):
    label: str
    value: float = Field(ge=0, le=1)
    tone: Tone


class BenchmarkRow(ViewModel):
    label: str
    value: str
    detail: str = ""
    segments: list[BenchmarkSegment] = Field(default_factory=list)


class BenchmarkChart(ViewModel):
    eyebrow: str = "Benchmark"
    title: str
    description: str = ""
    rows: list[BenchmarkRow]
    legend: list[BenchmarkLegendItem] = Field(default_factory=list)
    footnote: str = ""


class ComparisonGroup(ViewModel):
    id: str
    label: str
    chart: BenchmarkChart


class Notice(ViewModel):
    text: str
    tone: Tone = "warn"
    details: list[str] = Field(default_factory=list)


class TableColumn(ViewModel):
    key: str
    label: str
    align: Alignment = "left"


class TableCell(ViewModel):
    value: str
    href: str | None = None
    title: str = ""
    tone: Tone = "neutral"


class TableRow(ViewModel):
    cells: dict[str, TableCell]
    search: str = ""


class DataTable(ViewModel):
    title: str
    description: str = ""
    columns: list[TableColumn]
    rows: list[TableRow]
    searchable: bool = False


class DetailSection(ViewModel):
    title: str
    data: Any
    warning: str = ""


class TraceToolCall(ViewModel):
    name: str
    arguments: Any


class TraceStep(ViewModel):
    step_id: str
    source: str
    label: str
    message: str = ""
    tool_calls: list[TraceToolCall] = Field(default_factory=list)
    observation: str = ""
    metrics: dict[str, Any] = Field(default_factory=dict)


class TracePresentation(ViewModel):
    schema_version: str = ""
    step_count: int = Field(ge=0)
    final_metrics: dict[str, Any] = Field(default_factory=dict)
    steps: list[TraceStep] = Field(default_factory=list)


class TrialPresentation(ViewModel):
    trial_id: str
    title: str
    summary: list[Metric]
    sections: list[DetailSection]
    trace: TracePresentation | None = None


class JobPresentation(ViewModel):
    schema_version: str = "compute-bazaar.viewer.job.v1"
    task: TaskInfo
    job_id: str
    started_at: str = ""
    finished_at: str = ""
    agent_count: int = Field(ge=0)
    trial_count: int = Field(ge=0)
    primary_score: Metric | None = None
    metrics: list[Metric]
    notices: list[Notice]
    agent_table: DataTable
    trial_table: DataTable
    trials: dict[str, TrialPresentation]
