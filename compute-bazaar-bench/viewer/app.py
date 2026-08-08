"""Local FastAPI viewer for Compute Bazaar evaluation reports."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from html import escape
import json
from pathlib import Path
import sys
from typing import Any, Sequence

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn

BENCH_ROOT = Path(__file__).resolve().parents[1]
if str(BENCH_ROOT) not in sys.path:
    sys.path.insert(0, str(BENCH_ROOT))

from viewer.presenters import load_job_presentation  # noqa: E402
from viewer.schema import (  # noqa: E402
    DataTable,
    JobPresentation,
    Metric,
    TaskInfo,
    TrialPresentation,
)

ASSET_ROOT = Path(__file__).with_name("assets")


STYLE = """
:root {
  color-scheme: dark;
  --bg: #0f1312;
  --panel: #151a18;
  --panel-deep: #111513;
  --panel-hover: #1b211e;
  --line: #303833;
  --line-strong: #566158;
  --text: #efede4;
  --muted: #a7a69f;
  --green: #b7d07b;
  --amber: #f3c888;
  --red: #dc8d78;
  --blue: #91aecb;
  --topbar-height: 52px;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 14px;
  letter-spacing: 0;
}
a { color: inherit; text-decoration: none; }
.topbar { height: var(--topbar-height); display: flex; align-items: center; min-width: 0; padding: 0 18px; border-bottom: 1px solid var(--line); background: var(--panel-deep); }
.shell { width: min(1480px, calc(100% - 32px)); margin: 0 auto; padding: 28px 0 56px; }
.page-header { display: flex; justify-content: space-between; gap: 24px; align-items: flex-start; margin-bottom: 24px; }
.compute-brand {
  display: block;
  flex: none;
  position: relative;
  width: 150px;
  height: 46px;
  overflow: visible;
  color: #142027;
  font-family: ui-sans-serif, system-ui, sans-serif;
  user-select: none;
}
.compute-brand-fallback { position: absolute; inset: 0; transition: opacity 160ms ease; }
.compute-brand-word { position: absolute; font-weight: 700; line-height: 1; letter-spacing: 0; }
.compute-brand-word.the { left: 4px; top: 6px; color: #b7d07b; font-size: 13px; transform: rotate(-4deg); }
.compute-brand-word.compute { left: 39px; top: 6px; color: #91aecb; font-size: 15px; transform: rotate(1deg); }
.compute-brand-word.bazaar { right: 27px; bottom: 3px; color: #f3c888; font-size: 14px; transform: rotate(-2deg); }
.compute-brand[data-embroidery-ready="true"] .compute-brand-fallback { opacity: 0; }
.compute-brand canvas { z-index: 1; }
@media (prefers-reduced-motion: reduce) {
  .compute-brand-fallback { transition: none; }
}
.page-heading { min-width: 0; padding-top: 1px; }
h1 { margin: 0 0 8px; font-size: 26px; line-height: 1.15; letter-spacing: 0; }
h2 { margin: 0; font-size: 15px; letter-spacing: 0; }
.eyebrow, .muted { color: var(--muted); }
.eyebrow { font-size: 12px; margin-bottom: 8px; text-transform: uppercase; }
.status { border: 1px solid var(--line-strong); padding: 7px 9px; border-radius: 4px; white-space: nowrap; }
.status.good { color: var(--green); border-color: #647548; }
.status.warn { color: var(--amber); border-color: #8b7048; }
.notice { border: 1px solid #705b3d; color: var(--amber); padding: 10px 12px; margin: 0 0 12px; }
.notice.info { border-color: #52697c; color: var(--blue); }
.notice.good { border-color: #647548; color: var(--green); }
.notice.bad { border-color: #885a4d; color: var(--red); }
.notice summary { cursor: pointer; list-style-position: outside; }
.notice ul { margin: 12px 0 0; padding-left: 22px; color: var(--muted); }
.notice li + li { margin-top: 7px; }
.note-preview {
  display: -webkit-box;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  color: var(--muted);
  line-height: 1.45;
}
.note-editor { margin: 0 0 24px; }
.note-editor textarea {
  width: 100%;
  min-height: 92px;
  resize: vertical;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 4px;
  background: var(--panel);
  color: var(--text);
  font: inherit;
  line-height: 1.45;
}
.note-actions { display: flex; align-items: center; gap: 12px; margin-top: 8px; }
.note-actions button {
  padding: 7px 11px;
  border: 1px solid var(--line-strong);
  border-radius: 4px;
  background: var(--panel);
  color: var(--text);
  font: inherit;
  cursor: pointer;
}
.note-actions button:hover { border-color: var(--text); }
.task-hero {
  display: grid;
  grid-template-columns: minmax(0, 3fr) minmax(300px, 2fr);
  gap: 0;
  padding: 8px 0 28px;
  border-bottom: 1px solid var(--line);
}
.task-description { max-width: 760px; margin: 14px 0 18px; color: var(--muted); font-family: ui-sans-serif, system-ui, sans-serif; font-size: 16px; line-height: 1.55; }
.task-disclosures { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); max-width: 860px; border-top: 1px solid var(--line); }
.task-disclosure { min-width: 0; padding: 12px 14px 0 0; }
.task-disclosure + .task-disclosure { border-left: 1px solid var(--line); padding-left: 14px; }
.task-disclosure summary { cursor: pointer; color: var(--blue); }
.task-disclosure pre { margin-bottom: 0; white-space: pre-wrap; }
.grader-info { display: grid; gap: 10px; margin: 14px 0 0; }
.grader-info div { display: grid; gap: 3px; }
.grader-info dt { color: var(--muted); font-size: 10px; text-transform: uppercase; }
.grader-info dd { margin: 0; line-height: 1.4; }
.task-actions {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  align-self: start;
  justify-self: center;
  width: min(300px, 100%);
  margin-top: 28px;
  gap: 8px;
}
.button {
  display: inline-flex;
  justify-content: center;
  align-items: center;
  min-height: 38px;
  padding: 8px 12px;
  border: 1px solid var(--line-strong);
  border-radius: 4px;
  background: var(--panel);
  color: var(--text);
  font: inherit;
  cursor: pointer;
}
.button:hover { border-color: var(--text); background: var(--panel-hover); }
.button.primary { border-color: #789248; background: var(--green); color: #111513; font-weight: 700; }
.button.primary:hover { background: #c5db91; }
dialog { width: min(620px, calc(100% - 24px)); border: 1px solid var(--line-strong); border-radius: 5px; background: var(--bg); color: var(--text); padding: 0; }
dialog::backdrop { background: rgb(0 0 0 / 72%); }
.dialog-head { display: flex; align-items: center; justify-content: space-between; gap: 20px; padding: 18px; border-bottom: 1px solid var(--line); }
.dialog-body { padding: 18px; }
.dialog-close { width: 34px; height: 34px; padding: 0; font-size: 20px; }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.field { display: grid; gap: 6px; }
.field.wide { grid-column: 1 / -1; }
.field label { color: var(--muted); font-size: 11px; text-transform: uppercase; }
.field input, .field select { width: 100%; min-height: 38px; padding: 8px 10px; border: 1px solid var(--line); border-radius: 4px; background: var(--panel); color: var(--text); font: inherit; }
.command-preview { white-space: pre-wrap; overflow-wrap: anywhere; min-height: 76px; margin: 16px 0 0; }
.dialog-actions { display: flex; justify-content: flex-end; align-items: center; gap: 12px; margin-top: 14px; }
.metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(145px, 1fr)); border: 1px solid var(--line); margin: 24px 0; }
.metric { min-height: 92px; padding: 14px; border-right: 1px solid var(--line); }
.metric:last-child { border-right: 0; }
.metric-label { color: var(--muted); font-size: 11px; text-transform: uppercase; }
.metric-value { font-size: 24px; margin-top: 12px; line-height: 1; }
.section { margin-top: 26px; }
.section-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; gap: 16px; }
.eval-list { border: 1px solid var(--line); }
.eval-row {
  display: grid;
  grid-template-columns: minmax(260px, 1.5fr) minmax(110px, 0.6fr) minmax(70px, 0.35fr) minmax(70px, 0.35fr) minmax(320px, 2fr);
  gap: 16px;
  align-items: center;
  min-height: 82px;
  padding: 14px;
  border-bottom: 1px solid var(--line);
}
.eval-row:last-child { border-bottom: 0; }
.eval-row:hover { background: var(--panel-hover); }
.eval-row .status { display: block; white-space: normal; }
.eval-name { font-size: 16px; font-weight: 700; }
.eval-cell-label { display: block; margin-bottom: 6px; color: var(--muted); font-size: 10px; text-transform: uppercase; }
input {
  width: min(360px, 100%);
  background: var(--panel);
  color: var(--text);
  border: 1px solid var(--line);
  border-radius: 4px;
  padding: 9px 10px;
  font: inherit;
}
.table-wrap { overflow-x: auto; border: 1px solid var(--line); }
table { width: 100%; border-collapse: collapse; min-width: 920px; }
th, td { padding: 11px 12px; text-align: left; border-bottom: 1px solid var(--line); vertical-align: top; }
th { color: var(--muted); font-size: 11px; text-transform: uppercase; background: var(--panel-deep); position: sticky; top: 0; }
tr:last-child td { border-bottom: 0; }
tbody tr:hover { background: var(--panel-hover); }
.num { text-align: right; font-variant-numeric: tabular-nums; }
.good { color: var(--green); }
.warn { color: var(--amber); }
.bad { color: var(--red); }
.info { color: var(--blue); }
.tag { display: inline-block; border: 1px solid var(--line-strong); border-radius: 3px; padding: 3px 5px; font-size: 11px; }
.empty { border: 1px solid var(--line); color: var(--muted); padding: 18px; }
.detail-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); border: 1px solid var(--line); }
.detail { padding: 14px; border-right: 1px solid var(--line); border-bottom: 1px solid var(--line); }
.detail:nth-child(2n) { border-right: 0; }
.detail-key { color: var(--muted); font-size: 11px; text-transform: uppercase; margin-bottom: 7px; }
pre { overflow: auto; background: var(--panel-deep); border: 1px solid var(--line); padding: 14px; line-height: 1.45; }
.back { display: inline-block; margin-bottom: 20px; color: var(--muted); }
@media (max-width: 980px) {
  .eval-row { grid-template-columns: minmax(220px, 2fr) repeat(3, minmax(100px, 1fr)); }
  .eval-row > :last-child { grid-column: 1 / -1; }
}
@media (max-width: 640px) {
  .shell { width: min(100% - 20px, 1480px); padding-top: 18px; }
  .topbar { padding-inline: 9px; }
  .page-header, .section-head { flex-direction: column; }
  .section-head { align-items: flex-start; }
  .status { max-width: 100%; white-space: normal; }
  .metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .detail-grid { grid-template-columns: 1fr; }
  .task-hero { grid-template-columns: 1fr; gap: 24px; }
  .task-disclosures { grid-template-columns: 1fr; }
  .task-disclosure + .task-disclosure { border-left: 0; padding-left: 0; }
  .task-actions { width: 100%; margin-top: 0; }
  .form-grid { grid-template-columns: 1fr; }
  .field.wide { grid-column: auto; }
  .detail { border-right: 0; }
  .eval-row { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .eval-row > :first-child, .eval-row > :last-child { grid-column: 1 / -1; }
}
"""


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot read viewer file {path}: {exc}") from exc


def _compute_bazaar_mark() -> str:
    return """<a class="compute-brand" href="/" data-compute-embroidery role="img" aria-label="The Compute Bazaar">
<span class="compute-brand-fallback" aria-hidden="true"><span class="compute-brand-word the">THE</span><span class="compute-brand-word compute">COMPUTE</span><span class="compute-brand-word bazaar">BAZAAR</span></span></a>"""


def _viewer_path(base_path: str, path: str) -> str:
    return f"{base_path}{path}" if base_path else path


def _layout(title: str, body: str, base_path: str) -> str:
    embroidery = _viewer_path(
        base_path, "/assets/compute-title/compute-title-embroidery.js"
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)}</title><style>{STYLE}</style><link rel="stylesheet" href="/terminal-assets/command.css?v=20260808-2"><link rel="stylesheet" href="/terminal-assets/perspective/command.css?v=20260808-2"></head>
<body data-terminal-workspace="eval"><header class="topbar">{_compute_bazaar_mark()}</header><main class="shell">{body}</main>
<script type="module" src="/terminal-assets/perspective/command.js?v=20260808-2"></script>
<script type="module">import {{ setupComputeTitleEmbroidery }} from "{embroidery}"; setupComputeTitleEmbroidery();</script></body></html>"""


def _discover_run_paths(source: Path) -> dict[str, dict[str, Path]]:
    source = source.resolve()
    if (source / "view.json").is_file():
        raw = _read_json(source / "view.json")
        if not isinstance(raw, dict):
            raise RuntimeError("view.json must be a JSON object")
        task = raw.get("task", {})
        return {
            str(task.get("slug") or "evaluation"): {
                str(raw.get("job_id") or source.name): source
            }
        }
    if (source / "protocol.json").is_file() and (source / "trials.json").is_file():
        protocol = _read_json(source / "protocol.json")
        if not isinstance(protocol, dict):
            raise RuntimeError("protocol.json must be a JSON object")
        eval_slug = (
            "reliability-is-blind"
            if protocol.get("schema_version") == "reliability-is-blind.protocol.v1"
            else str(protocol.get("eval_slug") or "evaluation")
        )
        run_id = str(protocol.get("protocol_id") or source.name)
        return {eval_slug: {run_id: source}}

    discovered: dict[str, dict[str, Path]] = {}
    for container in ("runs", "jobs"):
        for run_dir in sorted(source.glob(f"*/{container}/*")):
            if not run_dir.is_dir():
                continue
            has_view = (run_dir / "view.json").is_file()
            has_analysis = (run_dir / "protocol.json").is_file() and (
                run_dir / "trials.json"
            ).is_file()
            if has_view or has_analysis:
                eval_slug = run_dir.parent.parent.name
                discovered.setdefault(eval_slug, {})[run_dir.name] = run_dir
    if not discovered:
        raise RuntimeError(
            "results root must contain <eval>/runs/<job>/view.json or "
            "protocol.json plus trials.json"
        )
    return discovered


class JobNote(BaseModel):
    text: str


def _read_note(run_dir: Path) -> dict[str, str]:
    path = run_dir / "notes.json"
    if not path.is_file():
        return {"text": "", "updated_at": ""}
    value = _read_json(path)
    if not isinstance(value, dict):
        raise RuntimeError("notes.json must be a JSON object")
    return {
        "text": str(value.get("text", "")),
        "updated_at": str(value.get("updated_at", "")),
    }


def _write_note(run_dir: Path, text: str) -> dict[str, str]:
    clean = text.strip()
    if len(clean) > 2000:
        raise HTTPException(
            status_code=422, detail="note must be at most 2000 characters"
        )
    value = {
        "text": clean,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    path = run_dir / "notes.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)
    return value


def _run_summary(
    presentation: JobPresentation, note: dict[str, str] | None = None
) -> dict[str, Any]:
    note = note or {"text": "", "updated_at": ""}
    return {
        "run_id": presentation.job_id,
        "score": presentation.primary_score,
        "agents": presentation.agent_count,
        "trials": presentation.trial_count,
        "note": note["text"],
        "note_updated_at": note["updated_at"],
    }


def _evaluation_summary(
    presentation: JobPresentation, *, job_count: int = 1
) -> dict[str, Any]:
    return {
        "slug": presentation.task.slug,
        "name": presentation.task.name,
        "domain": presentation.task.domain,
        "jobs": job_count,
        "agents": presentation.agent_count,
        "trials": presentation.trial_count,
    }


def _evals_html(evaluations: Sequence[dict[str, Any]], base_path: str = "") -> str:
    rows = "".join(
        f"""<a class="eval-row" href="{_viewer_path(base_path, f"/evals/{escape(item['slug'])}")}">
<div><span class="eval-cell-label">Task</span><div class="eval-name">{escape(item["name"])}</div></div>
<div><span class="eval-cell-label">Domain</span>{escape(item["domain"])}</div>
<div><span class="eval-cell-label">Jobs</span>{item["jobs"]}</div>
<div><span class="eval-cell-label">Agents</span>{item["agents"]}</div>
<div><span class="eval-cell-label">Trials</span>{item["trials"]}</div>
</a>"""
        for item in evaluations
    )
    body = f"""<section><div class="section-head"><h2>Tasks</h2></div><div class="eval-list">{rows}</div></section>"""
    return _layout("Tasks", body, base_path)


def _task_hero_html(task: TaskInfo, base_path: str) -> str:
    description = (
        f'<p class="task-description">{escape(task.description)}</p>'
        if task.description
        else ""
    )
    instruction = (
        f'<details class="task-disclosure"><summary>Agent instruction</summary><pre>{escape(task.instruction)}</pre></details>'
        if task.instruction
        else ""
    )
    grader = ""
    if task.grader:
        grader_rows = [
            ("Type", task.grader.kind),
            ("Primary reward", task.grader.primary_reward),
            ("Incomplete", task.grader.incomplete_outcome),
            ("Metrics", task.grader.metrics),
            ("Integrity", task.grader.integrity),
        ]
        grader_details = "".join(
            f"<div><dt>{escape(label)}</dt><dd>{escape(value)}</dd></div>"
            for label, value in grader_rows
        )
        grader = (
            '<details class="task-disclosure"><summary>Grader</summary>'
            f'<dl class="grader-info">{grader_details}</dl></details>'
        )
    disclosures = (
        f'<div class="task-disclosures">{instruction}{grader}</div>'
        if instruction or grader
        else ""
    )
    links = "".join(
        f'<a class="button" href="{escape(link.href)}" target="_blank" rel="noreferrer">{escape(link.label)} ↗</a>'
        for link in task.links
    )
    launcher = ""
    dialog = ""
    if task.launch:
        launch = task.launch
        launcher = '<button class="button primary" id="open-launch" type="button">Launch job</button>'
        spec = json.dumps(launch.model_dump()).replace("<", "\\u003c")
        dialog = f"""<dialog id="launch-dialog"><div class="dialog-head"><div><div class="eyebrow">Harbor</div><h2>Launch job</h2></div><button class="button dialog-close" id="close-launch" type="button" aria-label="Close">×</button></div><div class="dialog-body"><div class="form-grid">
<div class="field"><label for="launch-agent">Agent</label><input id="launch-agent" value="{escape(launch.default_agent)}"></div>
<div class="field"><label for="launch-model">Model</label><input id="launch-model" placeholder="provider/model"></div>
<div class="field"><label for="launch-environment">Environment</label><select id="launch-environment"><option value="{escape(launch.default_environment)}">{escape(launch.default_environment.title())}</option></select></div>
<div class="field"><label for="launch-attempts">Attempts</label><input id="launch-attempts" type="number" min="1" max="100" value="1"></div>
<div class="field"><label for="launch-concurrency">Concurrency</label><input id="launch-concurrency" type="number" min="1" max="100" value="1"></div>
<div class="field"><label for="launch-name">Job name</label><input id="launch-name" value="{escape(task.slug)}-job-001"></div>
</div><pre class="command-preview" id="launch-command"></pre><div class="dialog-actions"><span class="muted" id="copy-state"></span><button class="button primary" id="copy-command" type="button">Copy command</button></div></div></dialog>
<script>
const launchSpec={spec};const launchDialog=document.getElementById('launch-dialog');
const launchFields=['launch-agent','launch-model','launch-environment','launch-attempts','launch-concurrency','launch-name'];
const shellQuote=value=>/^[A-Za-z0-9_./:@+-]+$/.test(value)?value:`'${{value.replaceAll("'", "'\\\"'\\\"'")}}'`;
const buildCommand=()=>{{const value=id=>document.getElementById(id).value.trim();const parts=['harbor','run','-p',launchSpec.package_path,'-i',launchSpec.task_id,'-a',value('launch-agent')];if(value('launch-model'))parts.push('-m',value('launch-model'));parts.push('-e',value('launch-environment'),'-o',launchSpec.default_jobs_dir,'-k',value('launch-attempts'),'-n',value('launch-concurrency'),'--job-name',value('launch-name'));document.getElementById('launch-command').textContent=parts.map(shellQuote).join(' ');}};
launchFields.forEach(id=>document.getElementById(id).addEventListener('input',buildCommand));buildCommand();
document.getElementById('open-launch').addEventListener('click',()=>launchDialog.showModal());
document.getElementById('close-launch').addEventListener('click',()=>launchDialog.close());
document.getElementById('copy-command').addEventListener('click',async()=>{{await navigator.clipboard.writeText(document.getElementById('launch-command').textContent);document.getElementById('copy-state').textContent='Copied';}});
</script>"""
    tasks_url = _viewer_path(base_path, "/")
    return f"""<section class="task-hero"><div><div class="eyebrow"><a class="info" href="{tasks_url}">Tasks</a> / {escape(task.domain)}</div><h1>{escape(task.name)}</h1>{description}{disclosures}</div><div class="task-actions">{launcher}{links}</div></section>{dialog}"""


def _runs_html(
    task: TaskInfo,
    runs: Sequence[dict[str, Any]],
    base_path: str = "",
) -> str:
    rows = "".join(
        f"""<a class="eval-row" href="{_viewer_path(base_path, f"/evals/{escape(task.slug)}/jobs/{escape(run['run_id'])}")}">
<div><span class="eval-cell-label">Job</span><div class="eval-name">{escape(run["run_id"])}</div></div>
<div title="{escape(run["score"].hint if run["score"] else "")}"><span class="eval-cell-label">{escape(run["score"].label if run["score"] else "Score")}</span>{escape(run["score"].value if run["score"] else "—")}</div>
<div><span class="eval-cell-label">Agents</span>{run["agents"]}</div>
<div><span class="eval-cell-label">Trials</span>{run["trials"]}</div>
<div><span class="eval-cell-label">Note</span><span class="note-preview" title="{escape(run["note"] or "No note yet")}">{escape(run["note"] or "No note yet")}</span></div>
</a>"""
        for run in runs
    )
    empty = (
        '<div class="empty">No jobs yet.</div>'
        if not rows
        else f'<div class="eval-list">{rows}</div>'
    )
    body = f"""{_task_hero_html(task, base_path)}
<section class="section"><div class="section-head"><h2>Jobs</h2></div>{empty}</section>"""
    return _layout(task.name, body, base_path)


def _metric_html(metric: Metric) -> str:
    title = f' title="{escape(metric.hint)}"' if metric.hint else ""
    return f"""<div class="metric {metric.tone}"{title}><div class="metric-label">{escape(metric.label)}</div><div class="metric-value">{escape(metric.value)}</div></div>"""


def _table_html(
    table: DataTable,
    eval_slug: str,
    job_id: str,
    table_id: str,
    base_path: str,
) -> str:
    if not table.columns:
        return ""
    headers = "".join(
        f'<th class="{"num" if column.align == "right" else ""}">{escape(column.label)}</th>'
        for column in table.columns
    )
    rows = []
    for row in table.rows:
        cells = []
        for column in table.columns:
            cell = row.cells.get(column.key)
            value = cell.value if cell else "—"
            content = escape(value)
            if cell and cell.href:
                href = _viewer_path(
                    base_path,
                    f"/evals/{escape(eval_slug)}/jobs/{escape(job_id)}/trials/"
                    f"{escape(cell.href)}",
                )
                content = f'<a class="info" href="{href}">{content}</a>'
            if cell and cell.tone != "neutral":
                content = f'<span class="tag {cell.tone}">{content}</span>'
            title = f' title="{escape(cell.title)}"' if cell and cell.title else ""
            css = "num" if column.align == "right" else ""
            cells.append(f'<td class="{css}"{title}>{content}</td>')
        rows.append(
            f'<tr data-search="{escape(row.search.lower())}">{"".join(cells)}</tr>'
        )
    search = ""
    script = ""
    if table.searchable:
        search = f'<input id="search-{table_id}" aria-label="Filter {escape(table.title)}" placeholder="Filter {escape(table.title.lower())}">'
        script = f"""<script>document.getElementById('search-{table_id}').addEventListener('input',event=>{{const value=event.target.value.toLowerCase();document.querySelectorAll('#{table_id} tr').forEach(row=>row.hidden=!row.dataset.search.includes(value));}});</script>"""
    description = (
        f'<span class="muted">{escape(table.description)}</span>'
        if table.description
        else ""
    )
    return f"""<section class="section"><div class="section-head"><div><h2>{escape(table.title)}</h2>{description}</div>{search}</div><div class="table-wrap"><table><thead><tr>{headers}</tr></thead><tbody id="{table_id}">{"".join(rows)}</tbody></table></div></section>{script}"""


def _index_html(
    presentation: JobPresentation,
    note: dict[str, str] | None = None,
    base_path: str = "",
) -> str:
    note = note or {"text": "", "updated_at": ""}
    task = presentation.task
    job_id = presentation.job_id
    rendered_notices = []
    for notice in presentation.notices:
        if notice.details:
            details = "".join(f"<li>{escape(item)}</li>" for item in notice.details)
            rendered_notices.append(
                f'<details class="notice {notice.tone}"><summary>{escape(notice.text)}</summary><ul>{details}</ul></details>'
            )
        else:
            rendered_notices.append(
                f'<div class="notice {notice.tone}">{escape(notice.text)}</div>'
            )
    notices = "".join(rendered_notices)
    metrics = list(presentation.metrics)
    if presentation.primary_score:
        metrics.insert(0, presentation.primary_score)
    metric_cards = "".join(_metric_html(metric) for metric in metrics)
    tasks_url = _viewer_path(base_path, "/")
    eval_url = _viewer_path(base_path, f"/evals/{escape(task.slug)}")
    note_url = _viewer_path(
        base_path, f"/api/evals/{escape(task.slug)}/jobs/{escape(job_id)}/note"
    )
    body = f"""
<header class="page-header"><div class="page-heading"><div class="eyebrow"><a class="info" href="{tasks_url}">Tasks</a> / <a class="info" href="{eval_url}">{escape(task.name)}</a> / Job</div><h1>{escape(job_id)}</h1></div></header>
<section class="note-editor"><div class="section-head"><h2>Note</h2><span class="muted">{escape(note["updated_at"])}</span></div>
<textarea id="job-note" maxlength="2000" aria-label="Job note" placeholder="Add context, caveats, or interpretation for this job">{escape(note["text"])}</textarea>
<div class="note-actions"><button id="save-note" type="button">Save note</button><span class="muted" id="note-state"></span></div></section>
{notices}<section class="metrics">{metric_cards}</section>
{_table_html(presentation.agent_table, task.slug, job_id, "agents", base_path)}
{_table_html(presentation.trial_table, task.slug, job_id, "trials", base_path)}
<script>
const save=document.getElementById('save-note');const state=document.getElementById('note-state');save.addEventListener('click',async()=>{{save.disabled=true;state.textContent='Saving…';try{{const response=await fetch('{note_url}',{{method:'POST',headers:{{'content-type':'application/json'}},body:JSON.stringify({{text:document.getElementById('job-note').value}})}});if(!response.ok)throw new Error('Save failed');state.textContent='Saved';}}catch(error){{state.textContent=error.message;}}finally{{save.disabled=false;}}}});
</script>"""
    return _layout(job_id, body, base_path)


def _trial_html(
    trial: TrialPresentation, presentation: JobPresentation, base_path: str
) -> str:
    details = "".join(
        f'<div class="detail {metric.tone}" title="{escape(metric.hint)}"><div class="detail-key">{escape(metric.label)}</div><div>{escape(metric.value)}</div></div>'
        for metric in trial.summary
    )
    sections = "".join(
        f'<section class="section"><div class="section-head"><h2>{escape(section.title)}</h2>{f'<span class="warn">{escape(section.warning)}</span>' if section.warning else ""}</div><pre>{escape(json.dumps(section.data, indent=2, sort_keys=True))}</pre></section>'
        for section in trial.sections
    )
    task = presentation.task
    tasks_url = _viewer_path(base_path, "/")
    eval_url = _viewer_path(base_path, f"/evals/{escape(task.slug)}")
    job_url = _viewer_path(
        base_path,
        f"/evals/{escape(task.slug)}/jobs/{escape(presentation.job_id)}",
    )
    body = f"""<a class="back" href="{job_url}">← {escape(presentation.job_id)}</a><header class="page-header"><div class="page-heading"><div class="eyebrow"><a class="info" href="{tasks_url}">Tasks</a> / <a class="info" href="{eval_url}">{escape(task.name)}</a> / Trial</div><h1>{escape(trial.title)}</h1></div></header><div class="detail-grid">{details}</div>{sections}"""
    return _layout(trial.title, body, base_path)


def create_app(results_source: Path, *, base_path: str = "") -> FastAPI:
    base_path = f"/{base_path.strip('/')}" if base_path.strip("/") else ""
    run_paths = _discover_run_paths(results_source)
    app = FastAPI(title="Compute Bazaar Evals", docs_url=None, redoc_url=None)
    app.mount("/assets", StaticFiles(directory=ASSET_ROOT), name="assets")

    def run_path(eval_slug: str, run_id: str) -> Path:
        path = run_paths.get(eval_slug, {}).get(run_id)
        if path is None:
            raise HTTPException(status_code=404, detail="run not found")
        return path

    def presentation(eval_slug: str, run_id: str) -> JobPresentation:
        return load_job_presentation(run_path(eval_slug, run_id), eval_slug, run_id)

    def run_summaries(eval_slug: str) -> list[dict[str, Any]]:
        paths = run_paths.get(eval_slug)
        if paths is None:
            raise HTTPException(status_code=404, detail="eval not found")
        return [
            _run_summary(
                presentation(eval_slug, run_id), _read_note(run_path(eval_slug, run_id))
            )
            for run_id in sorted(paths)
        ]

    def latest_run_id(eval_slug: str) -> str:
        paths = run_paths.get(eval_slug)
        if not paths:
            raise HTTPException(status_code=404, detail="eval not found")
        return max(
            paths,
            key=lambda run_id: max(
                path.stat().st_mtime
                for path in (
                    paths[run_id] / "view.json",
                    paths[run_id] / "protocol.json",
                )
                if path.is_file()
            ),
        )

    def evaluation_summaries() -> list[dict[str, Any]]:
        summaries = []
        for eval_slug, paths in sorted(run_paths.items()):
            latest = latest_run_id(eval_slug)
            summaries.append(
                _evaluation_summary(
                    presentation(eval_slug, latest), job_count=len(paths)
                )
            )
        return summaries

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return _evals_html(evaluation_summaries(), base_path)

    @app.get("/evals/{eval_slug}", response_class=HTMLResponse)
    def evaluation(eval_slug: str) -> str:
        latest = presentation(eval_slug, latest_run_id(eval_slug))
        return _runs_html(latest.task, run_summaries(eval_slug), base_path)

    @app.get("/evals/{eval_slug}/jobs/{run_id}", response_class=HTMLResponse)
    def job_detail(eval_slug: str, run_id: str) -> str:
        return _index_html(
            presentation(eval_slug, run_id),
            _read_note(run_path(eval_slug, run_id)),
            base_path,
        )

    @app.get(
        "/evals/{eval_slug}/jobs/{run_id}/trials/{trial_name}",
        response_class=HTMLResponse,
    )
    def trial_detail(eval_slug: str, run_id: str, trial_name: str) -> str:
        job = presentation(eval_slug, run_id)
        match = job.trials.get(trial_name)
        if match is None:
            raise HTTPException(status_code=404, detail="trial not found")
        return _trial_html(match, job, base_path)

    @app.get("/api/evals")
    def evals_api() -> list[dict[str, Any]]:
        return evaluation_summaries()

    @app.get("/api/evals/{eval_slug}/jobs")
    def runs_api(eval_slug: str) -> list[dict[str, Any]]:
        return run_summaries(eval_slug)

    @app.get("/api/evals/{eval_slug}/jobs/{run_id}")
    def run_api(eval_slug: str, run_id: str) -> dict[str, Any]:
        return presentation(eval_slug, run_id).model_dump()

    @app.post("/api/evals/{eval_slug}/jobs/{run_id}/note")
    def save_job_note(eval_slug: str, run_id: str, note: JobNote) -> dict[str, str]:
        return _write_note(run_path(eval_slug, run_id), note.text)

    @app.get("/api/evals/{eval_slug}/jobs/{run_id}/trials")
    def run_trials_api(eval_slug: str, run_id: str) -> list[dict[str, Any]]:
        return [
            trial.model_dump()
            for trial in presentation(eval_slug, run_id).trials.values()
        ]

    @app.get("/api/protocol")
    def protocol_api() -> dict[str, Any]:
        eval_slug = next(iter(run_paths))
        return presentation(eval_slug, latest_run_id(eval_slug)).model_dump()

    @app.get("/api/trials")
    def trials_api() -> list[dict[str, Any]]:
        eval_slug = next(iter(run_paths))
        job = presentation(eval_slug, latest_run_id(eval_slug))
        return [trial.model_dump() for trial in job.trials.values()]

    return app


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="compute-bazaar-evals")
    parser.add_argument("results_source", type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8084)
    args = parser.parse_args(argv)
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        parser.error("private evaluator data may only bind to localhost")
    uvicorn.run(create_app(args.results_source), host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
