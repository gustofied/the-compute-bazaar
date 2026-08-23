"""Local FastAPI viewer for Compute Bazaar tasks, jobs, and reports."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from html import escape
import json
from pathlib import Path
import sys
from typing import Any, Sequence
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn

BENCH_ROOT = Path(__file__).resolve().parents[1]
if str(BENCH_ROOT) not in sys.path:
    sys.path.insert(0, str(BENCH_ROOT))

from viewer.comparisons import (  # noqa: E402
    build_job_comparison,
    comparison_references,
    discover_comparisons,
    task_comparison_references,
)
from viewer.presenters import load_job_presentation  # noqa: E402
from viewer.harbor_jobs import (  # noqa: E402
    present_harbor_job,
    summarize_harbor_job,
)
from viewer.job_sources import (  # noqa: E402
    JobSource,
    discover_job_sources,
)
from viewer.report_overlays import apply_report_overlay  # noqa: E402
from viewer.task_catalog import discover_task_definitions  # noqa: E402
from viewer.schema import (  # noqa: E402
    ComparisonCell,
    ComparisonPresentation,
    ComparisonReference,
    DataTable,
    JobPresentation,
    Metric,
    TableCell,
    TaskInfo,
    TracePresentation,
    TrialPresentation,
)

ASSET_ROOT = Path(__file__).with_name("assets")


STYLE = """
:root {
  color-scheme: dark;
  --bg: #090e11;
  --panel: #0d1418;
  --panel-deep: #090e11;
  --panel-hover: #121c21;
  --line: #243139;
  --line-strong: #3b4e59;
  --text: #e5e9e7;
  --muted: #8e9a9c;
  --green: #b7d07b;
  --amber: #f3c888;
  --red: #dc8d78;
  --blue: #91aecb;
  --topbar-height: 44px;
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
.topbar { height: var(--topbar-height); display: flex; align-items: center; justify-content: space-between; gap: 24px; min-width: 0; padding: 0 18px; border-bottom: 1px solid var(--line); background: var(--panel-deep); }
.topnav { display: flex; align-items: stretch; height: 100%; }
.topnav a { display: inline-flex; align-items: center; padding: 0 13px; color: var(--muted); font-size: 12px; }
.topnav a:hover, .topnav a[aria-current="page"] { color: var(--text); background: var(--panel-hover); }
.shell { width: min(1480px, calc(100% - 24px)); margin: 0 auto; padding: 12px 0 56px; }
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
.note-editor { margin: 0 0 20px; border: 1px solid var(--line); background: var(--panel); }
.note-editor summary { display: flex; justify-content: space-between; align-items: center; gap: 16px; min-height: 44px; padding: 10px 12px; cursor: pointer; list-style: none; }
.note-editor summary::-webkit-details-marker { display: none; }
.note-editor summary::after { content: "+"; color: var(--muted); }
.note-editor[open] summary::after { content: "-"; }
.note-editor-body { padding: 0 12px 12px; }
.note-editor textarea {
  width: 100%;
  min-height: 76px;
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
.button.primary { border-color: var(--blue); background: var(--blue); color: #111513; font-weight: 700; }
.button.primary:hover { border-color: var(--blue); background: var(--blue); filter: brightness(1.08); }
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
.metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); margin: 24px 0; border-top: 1px solid var(--line); border-left: 1px solid var(--line); }
.metric { min-height: 80px; padding: 12px; border-right: 1px solid var(--line); border-bottom: 1px solid var(--line); background: var(--bg); }
.metric-label { color: var(--muted); font-size: 10px; text-transform: uppercase; }
.metric-value { margin-top: 8px; overflow-wrap: anywhere; font-size: 18px; line-height: 1.35; }
.job-header h1 { max-width: 100%; overflow-wrap: anywhere; font-size: 20px; line-height: 1.4; }
.comparison-cards { display: grid; gap: 1px; border: 1px solid var(--line); background: var(--line); }
.comparison-card { display: grid; grid-template-columns: minmax(240px, 1fr) repeat(3, minmax(100px, auto)); gap: 18px; align-items: center; min-height: 78px; padding: 14px; background: var(--bg); }
.comparison-card:hover { background: var(--panel-hover); }
.comparison-card strong { display: block; margin-bottom: 5px; font-size: 15px; }
.comparison-card-copy { color: var(--muted); font-family: ui-sans-serif, system-ui, sans-serif; line-height: 1.4; }
.comparison-page-head { display: grid; grid-template-columns: minmax(0, 1fr) minmax(280px, 420px); gap: 36px; padding-bottom: 26px; border-bottom: 1px solid var(--line); }
.comparison-page-head h1 { font-size: 28px; }
.comparison-description { max-width: 800px; margin: 12px 0 0; color: var(--muted); font-family: ui-sans-serif, system-ui, sans-serif; font-size: 16px; line-height: 1.55; }
.metric-definition { display: grid; align-content: start; gap: 5px; padding: 14px 0 14px 18px; border-left: 2px solid var(--blue); }
.metric-definition span { color: var(--muted); font-size: 10px; text-transform: uppercase; }
.metric-definition strong { font-size: 16px; }
.metric-definition p { margin: 0; color: var(--muted); font-family: ui-sans-serif, system-ui, sans-serif; line-height: 1.45; }
.comparison-matrix-wrap { overflow-x: auto; border: 1px solid var(--line); }
.comparison-matrix { min-width: 960px; table-layout: fixed; }
.comparison-matrix th:first-child { width: 260px; }
.comparison-matrix th { position: static; }
.comparison-matrix td { padding: 0; }
.comparison-agent { padding: 15px 14px; }
.comparison-agent strong { display: block; line-height: 1.35; }
.comparison-agent span { display: block; margin-top: 5px; color: var(--muted); font-size: 11px; }
.comparison-cell { display: block; min-height: 124px; padding: 14px; border-left: 1px solid var(--line); }
.comparison-cell:hover { background: var(--panel-hover); }
.comparison-primary { display: block; font-size: 21px; font-weight: 700; font-variant-numeric: tabular-nums; }
.comparison-primary-label { display: block; margin-top: 3px; color: var(--muted); font-size: 10px; text-transform: uppercase; }
.comparison-secondary { display: flex; flex-wrap: wrap; gap: 5px 12px; margin-top: 13px; color: var(--muted); font-size: 11px; line-height: 1.35; }
.comparison-secondary strong { color: var(--text); font-weight: 500; }
.attempt-range { position: relative; height: 18px; margin-top: 12px; border-top: 1px solid var(--line-strong); }
.attempt-range::before, .attempt-range::after { content: ""; position: absolute; top: -3px; width: 1px; height: 5px; background: var(--line-strong); }
.attempt-range::before { left: 0; }
.attempt-range::after { right: 0; }
.attempt-dot { position: absolute; top: -4px; width: 7px; height: 7px; margin-left: -3px; border-radius: 50%; background: var(--blue); }
.attempt-range-label { position: absolute; top: 7px; right: 0; color: var(--muted); font-size: 9px; }
.comparison-counts { display: grid; grid-template-columns: minmax(260px, 1.5fr) repeat(var(--count-columns), minmax(80px, 0.55fr)); border: 1px solid var(--line); border-bottom: 0; }
.comparison-counts > div { min-height: 46px; padding: 11px 12px; border-right: 1px solid var(--line); border-bottom: 1px solid var(--line); font-variant-numeric: tabular-nums; }
.comparison-counts-head { color: var(--muted); font-size: 10px; text-transform: uppercase; background: var(--panel-deep); }
.comparison-counts-agent { font-weight: 700; }
.comparison-notes { margin: 12px 0 0; padding-left: 18px; color: var(--muted); font-family: ui-sans-serif, system-ui, sans-serif; line-height: 1.5; }
.comparison-notes li + li { margin-top: 5px; }
.comparison-method { border-top: 1px solid var(--line); padding-top: 14px; }
.comparison-method summary { width: max-content; cursor: pointer; color: var(--blue); }
.comparison-method-body { max-width: 860px; padding-top: 4px; }
.comparison-provenance { display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: 8px 14px; margin-top: 18px; color: var(--muted); }
.comparison-provenance code { overflow-wrap: anywhere; }
.comparison-provenance ul { margin: 0; padding-left: 18px; overflow-wrap: anywhere; }
.job-compare { margin-top: 10px; }
.job-compare-actions { display: flex; align-items: center; justify-content: space-between; gap: 14px; margin-bottom: 10px; }
.job-compare-actions .button:disabled { opacity: 0.45; cursor: not-allowed; }
.job-select-row { display: grid; grid-template-columns: 38px minmax(0, 1fr); border-bottom: 1px solid var(--line); }
.job-select-row:last-child { border-bottom: 0; }
.job-select-control { display: flex; align-items: center; justify-content: center; border-right: 1px solid var(--line); background: var(--panel-deep); cursor: pointer; }
.job-select-control input { width: 15px; height: 15px; padding: 0; accent-color: var(--blue); }
.job-select-row .eval-row { border-bottom: 0; }
.comparison-empty { color: var(--muted); }
.section { margin-top: 26px; }
.section-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; gap: 16px; }
.eval-tabs { display: flex; gap: 18px; height: 30px; margin-bottom: 12px; border-bottom: 1px solid var(--line); }
.eval-tabs a { position: relative; display: inline-flex; align-items: center; color: var(--muted); font-size: 10px; text-transform: uppercase; }
.eval-tabs a::after { position: absolute; right: 0; bottom: -1px; left: 0; height: 1px; background: transparent; content: ""; }
.eval-tabs a:hover, .eval-tabs a[aria-current="page"] { color: var(--text); }
.eval-tabs a[aria-current="page"]::after { background: var(--blue); }
.eval-list { border: 1px solid var(--line); }
.eval-row {
  display: grid;
  grid-template-columns: minmax(260px, 1.5fr) minmax(110px, 0.6fr) minmax(70px, 0.35fr) minmax(70px, 0.35fr) minmax(320px, 2fr);
  gap: 16px;
  align-items: center;
  min-height: 58px;
  padding: 10px 12px;
  border-bottom: 1px solid var(--line);
}
.job-row {
  grid-template-columns: minmax(260px, 1.5fr) minmax(110px, 0.55fr) minmax(165px, 0.8fr) minmax(70px, 0.35fr) minmax(70px, 0.35fr) minmax(260px, 1.5fr);
}
.eval-row:last-child { border-bottom: 0; }
.eval-row:hover { background: var(--panel-hover); }
.eval-row .status { display: block; white-space: normal; }
.eval-name { font-size: 14px; font-weight: 700; }
.eval-cell-label { display: block; margin-bottom: 3px; color: var(--muted); font-size: 9px; text-transform: uppercase; }
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
.trace-head { display: flex; align-items: baseline; gap: 12px; margin-bottom: 10px; }
.trace-list { border: 1px solid var(--line); }
.trace-step { border-bottom: 1px solid var(--line); background: var(--panel); }
.trace-step:last-child { border-bottom: 0; }
.trace-step[open] { background: var(--panel-deep); }
.trace-step summary { display: grid; grid-template-columns: 68px 80px minmax(0, 1fr) auto; gap: 12px; align-items: center; min-height: 48px; padding: 10px 12px; cursor: pointer; list-style: none; }
.trace-step summary::-webkit-details-marker { display: none; }
.trace-step summary::before { content: "+"; grid-column: 1; grid-row: 1; justify-self: end; color: var(--muted); }
.trace-step[open] summary::before { content: "-"; }
.trace-number { grid-column: 1; grid-row: 1; color: var(--muted); }
.trace-source { color: var(--blue); text-transform: uppercase; font-size: 11px; }
.trace-label { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.trace-usage { color: var(--muted); font-size: 11px; font-variant-numeric: tabular-nums; }
.trace-body { padding: 0 12px 14px 80px; }
.trace-block + .trace-block { margin-top: 12px; }
.trace-block-label { margin-bottom: 5px; color: var(--muted); font-size: 10px; text-transform: uppercase; }
.trace-body pre { max-height: 460px; margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; }
.trace-tool + .trace-tool { margin-top: 8px; }
.trace-tool-name { display: inline-block; margin-bottom: 5px; color: var(--blue); }
.back { display: inline-block; margin-bottom: 20px; color: var(--muted); }
@media (max-width: 980px) {
  .eval-row { grid-template-columns: minmax(220px, 2fr) repeat(3, minmax(100px, 1fr)); }
  .eval-row > :last-child { grid-column: 1 / -1; }
  .job-row { grid-template-columns: minmax(220px, 2fr) minmax(110px, 1fr) minmax(165px, 1.2fr) repeat(2, minmax(80px, 0.6fr)); }
}
body.terminal-shell-open .eval-row {
    grid-template-columns: minmax(220px, 2fr) repeat(3, minmax(100px, 1fr));
}
body.terminal-shell-open .eval-row > :last-child { grid-column: 1 / -1; }
body.terminal-shell-open .job-row {
  grid-template-columns: minmax(220px, 2fr) minmax(110px, 1fr) minmax(165px, 1.2fr) repeat(2, minmax(80px, 0.6fr));
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
  .topnav a { padding-inline: 8px; }
  .comparison-card { grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
  .comparison-card > :first-child { grid-column: 1 / -1; }
  .comparison-page-head { grid-template-columns: 1fr; gap: 20px; }
  .metric-definition { padding-left: 12px; }
  .comparison-counts { overflow-x: auto; grid-template-columns: minmax(190px, 1fr) repeat(var(--count-columns), minmax(76px, 0.55fr)); }
  .job-compare-actions { align-items: flex-start; flex-direction: column; }
  .form-grid { grid-template-columns: 1fr; }
  .field.wide { grid-column: auto; }
  .detail { border-right: 0; }
  .trace-step summary { grid-template-columns: 56px minmax(0, 1fr); }
  .trace-number { grid-column: 1; }
  .trace-source { grid-column: 2; }
  .trace-label { grid-column: 2; }
  .trace-usage { display: none; }
  .trace-body { padding-left: 12px; }
  .eval-row { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .eval-row > :first-child, .eval-row > :last-child { grid-column: 1 / -1; }
}
"""


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot read viewer file {path}: {exc}") from exc


def _parse_timestamp(value: str) -> datetime | None:
    clean = value.strip()
    if not clean:
        return None
    if clean.endswith("Z"):
        clean = f"{clean[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(clean)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_timestamp(value: str) -> str:
    parsed = _parse_timestamp(value)
    return "—" if parsed is None else parsed.strftime("%d %b %Y, %H:%M")


def _timestamp_sort_key(value: str) -> float:
    parsed = _parse_timestamp(value)
    return float("-inf") if parsed is None else parsed.timestamp()


def _compute_bazaar_mark(base_path: str) -> str:
    if base_path:
        return '<a class="terminal-wordmark" href="/" aria-label="The Compute Bazaar"><img src="/terminal-wordmark.png" alt="The Compute Bazaar"></a>'
    return f"""<a class="compute-brand" href="{_viewer_path(base_path, "/")}" data-compute-embroidery role="img" aria-label="The Compute Bazaar">
<span class="compute-brand-fallback" aria-hidden="true"><span class="compute-brand-word the">THE</span><span class="compute-brand-word compute">COMPUTE</span><span class="compute-brand-word bazaar">BAZAAR</span></span></a>"""


def _viewer_path(base_path: str, path: str) -> str:
    return f"{base_path}{path}" if base_path else path


def _layout(title: str, body: str, base_path: str) -> str:
    embroidery = _viewer_path(
        base_path, "/assets/compute-title/compute-title-embroidery.js"
    )
    if base_path:
        terminal_nav = f"""<header class="topbar terminal-topbar">{_compute_bazaar_mark(base_path)}<nav class="terminal-workspace-nav" aria-label="Terminal workspaces"><a href="/data">Data</a><a href="/fleet">Fleet</a><a href="{_viewer_path(base_path, "/")}" aria-current="page">Eval</a><span aria-disabled="true">Trade</span></nav></header>"""
    else:
        terminal_nav = f"""<header class="topbar">{_compute_bazaar_mark(base_path)}<nav class="topnav" aria-label="Evaluation viewer"><a href="{_viewer_path(base_path, "/")}">Tasks</a><a href="{_viewer_path(base_path, "/comparisons")}">Tourneys</a></nav></header>"""
    current = "tourneys" if title == "Tourneys" or ">Tourneys</a>" in body else "tasks"
    local_nav = (
        ""
        if not base_path
        else f"""<nav class="eval-tabs" aria-label="Eval views"><a href="{_viewer_path(base_path, "/")}"{' aria-current="page"' if current == "tasks" else ""}>Tasks</a><a href="{_viewer_path(base_path, "/comparisons")}"{' aria-current="page"' if current == "tourneys" else ""}>Tourneys</a></nav>"""
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)}</title><style>{STYLE}</style><link rel="stylesheet" href="/terminal-assets/chrome.css?v=20260823-4"><link rel="stylesheet" href="/terminal-assets/command.css?v=20260823-4"><link rel="stylesheet" href="/terminal-assets/perspective/command.css?v=20260808-2"></head>
<body data-terminal-workspace="eval">{terminal_nav}<main class="shell">{local_nav}{body}</main>
<script type="module" src="/terminal-assets/perspective/command.js?v=20260823-5"></script>
<script type="module">import {{ setupComputeTitleEmbroidery }} from "{embroidery}"; setupComputeTitleEmbroidery();</script></body></html>"""


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
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "notes.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)
    return value


def _run_summary(
    presentation: JobPresentation, note: dict[str, str] | None = None
) -> dict[str, Any]:
    note = note or {"text": "", "updated_at": ""}
    origin = next(
        (
            metric.value
            for metric in presentation.metrics
            if metric.label == "Execution origin"
        ),
        "",
    )
    return {
        "run_id": presentation.job_id,
        "started_at": presentation.started_at,
        "finished_at": presentation.finished_at,
        "started": _format_timestamp(presentation.started_at),
        "score": presentation.primary_score,
        "agents": presentation.agent_count,
        "trials": presentation.trial_count,
        "note": note["text"],
        "note_updated_at": note["updated_at"],
        "origin": origin,
    }


def _evaluation_summary(
    task: TaskInfo,
    *,
    jobs: int,
    agent_configurations: set[tuple[str, str]],
    trials: int,
) -> dict[str, Any]:
    return {
        "slug": task.slug,
        "name": task.name,
        "domain": task.domain,
        "jobs": jobs,
        "agents": len(agent_configurations),
        "trials": trials,
    }


def _empty_evaluation_summary(task: TaskInfo) -> dict[str, Any]:
    return {
        "slug": task.slug,
        "name": task.name,
        "domain": task.domain,
        "jobs": 0,
        "agents": 0,
        "trials": 0,
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
    native_link_attribute = ' data-external-link="true"' if base_path else ""
    links = "".join(
        f'<a class="button" href="{escape(link.href)}" target="_blank" '
        f'rel="noreferrer"{native_link_attribute}>{escape(link.label)} ↗</a>'
        for link in task.links
    )
    external_link_script = (
        """<script>
document.querySelectorAll('[data-external-link]').forEach(link=>link.addEventListener('click',async event=>{event.preventDefault();try{const response=await fetch('/api/terminal/external',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url:link.href})});if(!response.ok)throw new Error('external open rejected');}catch(_error){window.location.assign(link.href);}}));
</script>"""
        if base_path and task.links
        else ""
    )
    launcher = ""
    dialog = ""
    if task.launch:
        launch = task.launch
        launcher = '<button class="button primary" id="open-launch" type="button">Launch job</button>'
        spec = json.dumps(launch.model_dump()).replace("<", "\\u003c")
        dialog = f"""<dialog id="launch-dialog"><div class="dialog-head"><div><div class="eyebrow">Harbor</div><h2>Launch job</h2></div><button class="button dialog-close" id="close-launch" type="button" aria-label="Close">×</button></div><div class="dialog-body"><div class="form-grid">
<div class="field"><label for="launch-agent">Agent</label><input id="launch-agent" value="{escape(launch.default_agent)}" autocapitalize="none" autocorrect="off" spellcheck="false"></div>
<div class="field"><label for="launch-model">Model</label><input id="launch-model" placeholder="provider/model" autocapitalize="none" autocorrect="off" spellcheck="false"></div>
<div class="field"><label for="launch-environment">Environment</label><select id="launch-environment"><option value="{escape(launch.default_environment)}">{escape(launch.default_environment.title())}</option></select></div>
<div class="field"><label for="launch-attempts">Attempts</label><input id="launch-attempts" type="number" min="1" max="100" value="1"></div>
<div class="field"><label for="launch-concurrency">Concurrency</label><input id="launch-concurrency" type="number" min="1" max="100" value="1"></div>
<div class="field"><label for="launch-name">Job name</label><input id="launch-name" autocapitalize="none" autocorrect="off" spellcheck="false"></div>
</div><pre class="command-preview" id="launch-command"></pre><div class="dialog-actions"><span class="muted" id="copy-state"></span><button class="button primary" id="copy-command" type="button">Copy command</button></div></div></dialog>
<script>
const launchSpec={spec};const launchDialog=document.getElementById('launch-dialog');
const launchFields=['launch-agent','launch-model','launch-environment','launch-attempts','launch-concurrency','launch-name'];
const shellQuote=value=>/^[A-Za-z0-9_./:@+-]+$/.test(value)?value:`'${{value.replaceAll("'", "'\\\"'\\\"'")}}'`;
const tmuxSession=value=>value.toLowerCase().replaceAll(/[^a-z0-9_-]/g,'-').replaceAll(/-+/g,'-').slice(0,80)||'compute-bazaar-eval';
const newJobName=()=>{{const now=new Date().toISOString();const stamp=now.slice(0,19).replaceAll('-','').replaceAll(':','').replace('T','-');const suffix=globalThis.crypto?.randomUUID?crypto.randomUUID().slice(0,6):Math.random().toString(36).slice(2,8);return `${{launchSpec.task_id}}-job-${{stamp}}-${{suffix}}`;}};
const buildCommand=()=>{{const value=id=>document.getElementById(id).value.trim();const environment=value('launch-environment');const attempts=value('launch-attempts');const parts=['harbor','run','--env-file',launchSpec.default_env_file,'-p',launchSpec.package_path,'-a',value('launch-agent')];if(value('launch-model'))parts.push('-m',value('launch-model'));parts.push('-e',environment);if(environment==='modal'&&launchSpec.modal_vm_runtime)parts.push('--ek','modal_vm_runtime=true');parts.push('-o',launchSpec.default_jobs_dir);if(attempts!=='1')parts.push('-k',attempts,'-n',value('launch-concurrency'));parts.push('--job-name',value('launch-name'));const harborCommand=parts.map(shellQuote).join(' ');const command=['tmux','new-session','-A','-s',tmuxSession(value('launch-name')),harborCommand];document.getElementById('launch-command').textContent=command.map(shellQuote).join(' ');}};
launchFields.forEach(id=>document.getElementById(id).addEventListener('input',buildCommand));document.getElementById('launch-name').value=newJobName();buildCommand();
document.getElementById('open-launch').addEventListener('click',()=>{{document.getElementById('launch-name').value=newJobName();buildCommand();launchDialog.showModal();}});
document.getElementById('close-launch').addEventListener('click',()=>launchDialog.close());
document.getElementById('copy-command').addEventListener('click',async()=>{{await navigator.clipboard.writeText(document.getElementById('launch-command').textContent);document.getElementById('copy-state').textContent='Copied';}});
</script>"""
    tasks_url = _viewer_path(base_path, "/")
    return f"""<section class="task-hero"><div><div class="eyebrow"><a class="info" href="{tasks_url}">Tasks</a> / {escape(task.domain)}</div><h1>{escape(task.name)}</h1>{description}{disclosures}</div><div class="task-actions">{launcher}{links}</div></section>{dialog}{external_link_script}"""


def _runs_html(
    task: TaskInfo,
    runs: Sequence[dict[str, Any]],
    base_path: str = "",
    comparisons: Sequence[ComparisonReference] = (),
) -> str:
    job_rows = []
    selectable_runs = [run for run in runs if run.get("comparable")]
    selectable = len(selectable_runs) >= 2
    for run in runs:
        card = f"""<a class="eval-row job-row" href="{_viewer_path(base_path, f"/evals/{escape(task.slug)}/jobs/{escape(run['run_id'])}")}">
<div><span class="eval-cell-label">Job</span><div class="eval-name">{escape(run["run_id"])}</div></div>
<div title="{escape(run["score"].hint if run["score"] else "")}"><span class="eval-cell-label">{escape(run["score"].label if run["score"] else "Score")}</span>{escape(run["score"].value if run["score"] else "—")}</div>
<div><span class="eval-cell-label">Started UTC</span>{escape(run["started"])}</div>
<div><span class="eval-cell-label">Agents</span>{run["agents"]}</div>
<div><span class="eval-cell-label">Trials</span>{run["trials"]}</div>
<div><span class="eval-cell-label">{"How scored" if run.get("origin") else "Note"}</span><span class="note-preview" title="{escape(run.get("origin") or run["note"] or "No note yet")}">{escape(run.get("origin") or run["note"] or "No note yet")}</span></div>
</a>"""
        if selectable and run.get("comparable"):
            card = (
                '<div class="job-select-row"><label class="job-select-control" '
                f'title="Select {escape(run["run_id"])} for comparison"><input '
                f'type="checkbox" name="job" value="{escape(run["run_id"])}" '
                f'aria-label="Select {escape(run["run_id"])}"></label>{card}</div>'
            )
        job_rows.append(card)
    rendered_job_rows = "".join(job_rows)
    if not rendered_job_rows:
        jobs = '<div class="empty">No jobs yet.</div>'
    elif not selectable:
        jobs = f'<div class="eval-list">{rendered_job_rows}</div>'
    else:
        jobs = (
            '<form class="job-compare" action="'
            f'{_viewer_path(base_path, "/comparisons/jobs")}" method="get">'
            f'<input type="hidden" name="task" value="{escape(task.slug)}">'
            '<div class="job-compare-actions"><span class="muted">Select two or more jobs for a direct Harbor comparison.</span>'
            '<button class="button" id="compare-jobs" type="submit" disabled>Compare selected</button></div>'
            f'<div class="eval-list">{rendered_job_rows}</div></form>'
            '<script>const compareForm=document.querySelector(".job-compare");if(compareForm){const boxes=[...compareForm.querySelectorAll("input[name=job]")];const button=document.getElementById("compare-jobs");const update=()=>button.disabled=boxes.filter(box=>box.checked).length<2;boxes.forEach(box=>box.addEventListener("change",update));}</script>'
        )
    comparison_section = _task_comparisons_html(
        comparisons,
        base_path,
    )
    body = f"""{_task_hero_html(task, base_path)}{comparison_section}
<section class="section"><div class="section-head"><h2>Jobs</h2></div>{jobs}</section>"""
    return _layout(task.name, body, base_path)


def _task_comparisons_html(
    comparisons: Sequence[ComparisonReference], base_path: str
) -> str:
    if not comparisons:
        return ""
    cards = "".join(
        '<a class="comparison-card" href="'
        f'{_viewer_path(base_path, f"/comparisons/{quote(item.id, safe='')}")}">'
        f'<div><strong>{escape(item.label)}</strong><span class="comparison-card-copy">{escape(item.description)}</span></div>'
        f'<div><span class="eval-cell-label">Primary</span>{escape(item.primary_metric)}</div>'
        f'<div><span class="eval-cell-label">Agents</span>{item.agent_count}</div>'
        f'<div><span class="eval-cell-label">Tasks</span>{len(item.task_slugs)}</div></a>'
        for item in comparisons
    )
    return f'<section class="section"><div class="section-head"><h2>Tourneys</h2></div><div class="comparison-cards">{cards}</div></section>'


def _comparisons_index_html(
    comparisons: Sequence[ComparisonReference], base_path: str
) -> str:
    body = (
        '<header class="page-header"><div class="page-heading"><div class="eyebrow">Evaluations</div><h1>Tourneys</h1><p class="task-description">Agents compared across the same tasks or market seeds.</p></div></header>'
        f"{_task_comparisons_html(comparisons, base_path)}"
    )
    return _layout("Tourneys", body, base_path)


def _comparison_page_html(
    comparison: ComparisonPresentation,
    base_path: str,
) -> str:
    task_columns = comparison.tasks
    show_overall = len(task_columns) > 1
    cells = {(cell.agent_id, cell.task_slug): cell for cell in comparison.cells}
    columns = ([None] if show_overall else []) + [task.slug for task in task_columns]
    labels = {task.slug: task.label for task in task_columns}
    if show_overall:
        labels[None] = "Overall"

    headers = '<th scope="col">Agent configuration</th>' + "".join(
        f'<th scope="col">{escape(labels[task_slug])}</th>' for task_slug in columns
    )
    matrix_rows = []
    for agent in comparison.agents:
        rendered_cells = []
        for task_slug in columns:
            cell = cells.get((agent.id, task_slug))
            rendered_cells.append(
                f"<td>{_comparison_cell_html(cell, comparison, task_slug, base_path)}</td>"
            )
        matrix_rows.append(
            '<tr><th scope="row"><div class="comparison-agent">'
            f"<strong>{escape(agent.label)}</strong>"
            f"<span>{escape(agent.execution_origin)}</span></div></th>"
            f"{''.join(rendered_cells)}</tr>"
        )

    definition = comparison.primary_metric
    secondary_definition = (
        '<div class="metric-definition"><span>Supporting metric</span>'
        f"<strong>{escape(comparison.secondary_metric.label)}</strong>"
        f"<p>{escape(comparison.secondary_metric.description)}</p></div>"
        if comparison.secondary_metric
        else ""
    )
    body = f"""<header class="comparison-page-head"><div><div class="eyebrow"><a class="info" href="{_viewer_path(base_path, "/comparisons")}">Tourneys</a></div><h1>{escape(comparison.label)}</h1><p class="comparison-description">{escape(comparison.description)}</p></div><div><div class="metric-definition"><span>Primary metric</span><strong>{escape(definition.label)}</strong><p>{escape(definition.description)}</p></div>{secondary_definition}</div></header>
<section class="section"><div class="section-head"><h2>Results</h2></div><div class="comparison-matrix-wrap"><table class="comparison-matrix"><thead><tr>{headers}</tr></thead><tbody>{"".join(matrix_rows)}</tbody></table></div></section>
{_comparison_counts_html(comparison)}
{_comparison_telemetry_html(comparison)}
{_comparison_attempts_html(comparison, base_path)}
{_comparison_notes_html(comparison)}"""
    return _layout(comparison.label, body, base_path)


def _comparison_cell_html(
    cell: ComparisonCell | None,
    comparison: ComparisonPresentation,
    task_slug: str | None,
    base_path: str,
) -> str:
    if cell is None:
        return '<div class="comparison-cell comparison-empty">No result</div>'
    secondary = "".join(
        "<span>"
        f"{escape(measure.label)} <strong>{escape(measure.value)}</strong>"
        f"{f' · {escape(measure.detail)}' if measure.detail else ''}</span>"
        for measure in cell.secondary
    )
    distribution = _attempt_range_html(cell.attempt_values)
    resolved_task = task_slug or comparison.tasks[0].slug
    href = _viewer_path(
        base_path,
        f"/evals/{quote(resolved_task, safe='')}/jobs/{quote(cell.job_id, safe='')}",
    )
    return (
        f'<a class="comparison-cell" href="{href}">'
        f'<strong class="comparison-primary {cell.primary.tone}">{escape(cell.primary.value)}</strong>'
        f'<span class="comparison-primary-label">{escape(cell.primary.label)}</span>'
        f'<div class="comparison-secondary">{secondary}</div>{distribution}</a>'
    )


def _attempt_range_html(values: Sequence[float]) -> str:
    clean = [float(value) for value in values if 0 <= float(value) <= 1]
    if len(clean) < 2 or len(clean) != len(values):
        return ""
    dots = "".join(
        f'<span class="attempt-dot" style="left:{100 * value:.4f}%" aria-hidden="true"></span>'
        for value in clean
    )
    return (
        '<div class="attempt-range" role="img" '
        f'aria-label="Attempt values from {100 * min(clean):.1f}% to {100 * max(clean):.1f}%">'
        f'{dots}<span class="attempt-range-label">{100 * min(clean):.1f}–{100 * max(clean):.1f}%</span></div>'
    )


def _comparison_counts_html(comparison: ComparisonPresentation) -> str:
    if not comparison.count_columns:
        return ""
    aggregate = {
        cell.agent_id: cell for cell in comparison.cells if cell.task_slug is None
    }
    if not aggregate and len(comparison.tasks) == 1:
        aggregate = {
            cell.agent_id: cell
            for cell in comparison.cells
            if cell.task_slug == comparison.tasks[0].slug
        }
    columns = len(comparison.count_columns)
    header = '<div class="comparison-counts-head">Agent configuration</div>' + "".join(
        f'<div class="comparison-counts-head" title="{escape(column.description)}">{escape(column.label)}</div>'
        for column in comparison.count_columns
    )
    rows = []
    for agent in comparison.agents:
        cell = aggregate.get(agent.id)
        values = "".join(
            f"<div>{cell.counts.get(column.key, 0) if cell else '—'}</div>"
            for column in comparison.count_columns
        )
        rows.append(
            f'<div class="comparison-counts-agent">{escape(agent.label)}</div>{values}'
        )
    return f'<section class="section"><div class="section-head"><div><h2>Attempts counted</h2><span class="muted">Planned, scored, and unscored attempts.</span></div></div><div class="comparison-counts" style="--count-columns:{columns}">{header}{"".join(rows)}</div></section>'


def _comparison_telemetry_html(comparison: ComparisonPresentation) -> str:
    if not comparison.telemetry_columns or not comparison.telemetry:
        return ""
    agents = {agent.id: agent for agent in comparison.agents}
    headers = '<th scope="col">Agent configuration</th>' + "".join(
        f'<th scope="col" class="num">{escape(column.label)}</th>'
        for column in comparison.telemetry_columns
    )
    rows = "".join(
        "<tr>"
        f"<td>{escape(agents[row.agent_id].label)}</td>"
        + "".join(
            f'<td class="num">{escape(row.values.get(column.key, "—"))}</td>'
            for column in comparison.telemetry_columns
        )
        + "</tr>"
        for row in comparison.telemetry
        if row.agent_id in agents
    )
    return f'<section class="section"><div class="section-head"><div><h2>Time and tokens</h2><span class="muted">Medians for context.</span></div></div><div class="table-wrap"><table><thead><tr>{headers}</tr></thead><tbody>{rows}</tbody></table></div></section>'


def _comparison_attempts_html(
    comparison: ComparisonPresentation, base_path: str
) -> str:
    if not comparison.attempts:
        return ""
    agents = {agent.id: agent for agent in comparison.agents}
    tasks = {task.slug: task.label for task in comparison.tasks}
    rows = []
    for attempt in comparison.attempts:
        href = _viewer_path(
            base_path,
            f"/evals/{quote(attempt.task_slug, safe='')}/jobs/{quote(attempt.job_id, safe='')}/trials/{quote(attempt.trial_id, safe='')}",
        )
        search = " ".join(
            (
                agents.get(attempt.agent_id).label
                if attempt.agent_id in agents
                else "",
                tasks.get(attempt.task_slug, attempt.task_slug),
                attempt.trial_id,
                attempt.status,
            )
        ).lower()
        rows.append(
            f'<tr data-search="{escape(search)}"><td><a class="info" href="{href}">{escape(attempt.trial_id)}</a></td>'
            f"<td>{escape(agents.get(attempt.agent_id).label if attempt.agent_id in agents else attempt.agent_id)}</td>"
            f"<td>{escape(tasks.get(attempt.task_slug, attempt.task_slug))}</td>"
            f'<td><span class="tag {attempt.tone}">{escape(attempt.status)}</span></td>'
            f'<td class="num">{escape(attempt.primary or "—")}</td>'
            f'<td class="num">{escape(attempt.secondary or "—")}</td>'
            f'<td class="num">{_duration_html(attempt.duration_seconds)}</td>'
            f'<td class="num">{_integer_html(attempt.input_tokens)}</td>'
            f'<td class="num">{_integer_html(attempt.output_tokens)}</td></tr>'
        )
    primary_label = escape(comparison.primary_metric.label)
    secondary_label = escape(
        comparison.secondary_metric.label
        if comparison.secondary_metric
        else "Supporting"
    )
    return f'<section class="section"><div class="section-head"><div><h2>Attempts</h2><span class="muted">Open a trial for its Harbor record.</span></div><input id="comparison-attempt-search" aria-label="Filter attempts" placeholder="Filter attempts"></div><div class="table-wrap"><table><thead><tr><th>Trial</th><th>Agent</th><th>Task</th><th>Status</th><th class="num">{primary_label}</th><th class="num">{secondary_label}</th><th class="num">Agent time</th><th class="num">Input</th><th class="num">Output</th></tr></thead><tbody id="comparison-attempts">{"".join(rows)}</tbody></table></div></section><script>document.getElementById("comparison-attempt-search").addEventListener("input",event=>{{const value=event.target.value.toLowerCase();document.querySelectorAll("#comparison-attempts tr").forEach(row=>row.hidden=!row.dataset.search.includes(value));}});</script>'


def _comparison_notes_html(comparison: ComparisonPresentation) -> str:
    notes = "".join(f"<li>{escape(note)}</li>" for note in comparison.notes)
    sources = "".join(
        f"<li>{escape(source)}</li>" for source in comparison.provenance.sources
    )
    return (
        '<section class="section"><details class="comparison-method">'
        '<summary>Method</summary><div class="comparison-method-body">'
        f'<ul class="comparison-notes">{notes}</ul>'
        f'<div class="comparison-provenance"><strong>Generated by</strong><code>{escape(comparison.provenance.generator)}</code>'
        f"<strong>Sources</strong><ul>{sources}</ul></div></div></details></section>"
    )


def _duration_html(value: float | None) -> str:
    if value is None:
        return "—"
    if value >= 60:
        return f"{int(value // 60)}m {value % 60:.0f}s"
    return f"{value:.1f}s"


def _integer_html(value: int | None) -> str:
    return f"{value:,}" if value is not None else "—"


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
    note_preview = note["text"] or "Add context or interpretation"
    body = f"""
<header class="page-header job-header"><div class="page-heading"><div class="eyebrow"><a class="info" href="{tasks_url}">Tasks</a> / <a class="info" href="{eval_url}">{escape(task.name)}</a> / Job</div><h1>{escape(job_id)}</h1></div></header>
<details class="note-editor"><summary><strong>Note</strong><span class="muted" id="note-preview">{escape(note_preview)}</span></summary><div class="note-editor-body">
<textarea id="job-note" maxlength="2000" aria-label="Job note" placeholder="Add context, caveats, or interpretation for this job">{escape(note["text"])}</textarea>
<div class="note-actions"><button id="save-note" type="button">Save note</button><span class="muted" id="note-state">{escape(note["updated_at"])}</span></div></div></details>
{notices}<section class="metrics">{metric_cards}</section>
{_table_html(presentation.agent_table, task.slug, job_id, "agents", base_path)}
{_table_html(presentation.trial_table, task.slug, job_id, "trials", base_path)}
<script>
const save=document.getElementById('save-note');const state=document.getElementById('note-state');const noteInput=document.getElementById('job-note');const notePreview=document.getElementById('note-preview');save.addEventListener('click',async()=>{{save.disabled=true;state.textContent='Saving…';try{{const response=await fetch('{note_url}',{{method:'POST',headers:{{'content-type':'application/json'}},body:JSON.stringify({{text:noteInput.value}})}});if(!response.ok)throw new Error('Save failed');notePreview.textContent=noteInput.value.trim()||'Add context or interpretation';state.textContent='Saved';}}catch(error){{state.textContent=error.message;}}finally{{save.disabled=false;}}}});
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
    trace = _trace_html(trial.trace) if trial.trace else ""
    task = presentation.task
    tasks_url = _viewer_path(base_path, "/")
    eval_url = _viewer_path(base_path, f"/evals/{escape(task.slug)}")
    job_url = _viewer_path(
        base_path,
        f"/evals/{escape(task.slug)}/jobs/{escape(presentation.job_id)}",
    )
    body = f"""<a class="back" href="{job_url}">← {escape(presentation.job_id)}</a><header class="page-header"><div class="page-heading"><div class="eyebrow"><a class="info" href="{tasks_url}">Tasks</a> / <a class="info" href="{eval_url}">{escape(task.name)}</a> / Trial</div><h1>{escape(trial.title)}</h1></div></header><div class="detail-grid">{details}</div>{trace}{sections}"""
    return _layout(trial.title, body, base_path)


def _trace_html(trace: TracePresentation) -> str:
    final_metrics = trace.final_metrics
    total_steps = final_metrics.get("total_steps", trace.step_count)
    prompt = final_metrics.get("total_prompt_tokens")
    completion = final_metrics.get("total_completion_tokens")
    meta = [f"{total_steps} steps"]
    if isinstance(prompt, (int, float)):
        meta.append(f"{int(prompt):,} input tokens")
    if isinstance(completion, (int, float)):
        meta.append(f"{int(completion):,} output tokens")
    if trace.schema_version:
        meta.append(trace.schema_version)

    rendered_steps = []
    for step in trace.steps:
        usage = []
        prompt_tokens = step.metrics.get("prompt_tokens")
        completion_tokens = step.metrics.get("completion_tokens")
        if isinstance(prompt_tokens, (int, float)):
            usage.append(f"{int(prompt_tokens):,} in")
        if isinstance(completion_tokens, (int, float)):
            usage.append(f"{int(completion_tokens):,} out")

        blocks = []
        if step.message:
            blocks.append(
                '<div class="trace-block"><div class="trace-block-label">Message</div>'
                f"<pre>{escape(step.message)}</pre></div>"
            )
        if step.tool_calls:
            tools = []
            for tool in step.tool_calls:
                arguments = json.dumps(tool.arguments, indent=2, sort_keys=True)
                tools.append(
                    '<div class="trace-tool">'
                    f'<code class="trace-tool-name">{escape(tool.name)}</code>'
                    f"<pre>{escape(arguments)}</pre></div>"
                )
            blocks.append(
                '<div class="trace-block"><div class="trace-block-label">Tool calls</div>'
                f"{''.join(tools)}</div>"
            )
        if step.observation:
            blocks.append(
                '<div class="trace-block"><div class="trace-block-label">Observation</div>'
                f"<pre>{escape(step.observation)}</pre></div>"
            )
        body = "".join(blocks) or '<span class="muted">No content recorded.</span>'
        rendered_steps.append(
            '<details class="trace-step"><summary>'
            f'<span class="trace-number">#{escape(step.step_id)}</span>'
            f'<span class="trace-source">{escape(step.source)}</span>'
            f'<strong class="trace-label">{escape(step.label)}</strong>'
            f'<span class="trace-usage">{escape(" · ".join(usage))}</span>'
            f'</summary><div class="trace-body">{body}</div></details>'
        )
    empty = '<div class="empty">No trajectory steps recorded.</div>'
    timeline = (
        f'<div class="trace-list">{"".join(rendered_steps)}</div>'
        if rendered_steps
        else empty
    )
    return (
        '<section class="section"><div class="trace-head"><h2>Trajectory</h2>'
        f'<span class="muted">{escape(" · ".join(meta))}</span></div>{timeline}</section>'
    )


def first_evaluation_url(
    results_source: Path, *, bench_root: Path | None = None
) -> str | None:
    root = bench_root or BENCH_ROOT
    slugs = set(discover_task_definitions(root)) | set(
        discover_job_sources(root, results_source)
    )
    return f"/eval/evals/{sorted(slugs)[0]}" if slugs else None


def create_app(
    results_source: Path,
    *,
    base_path: str = "",
    bench_root: Path | None = None,
) -> FastAPI:
    base_path = f"/{base_path.strip('/')}" if base_path.strip("/") else ""
    root = bench_root or BENCH_ROOT
    task_definitions = discover_task_definitions(root)
    job_sources = discover_job_sources(root, results_source)
    comparisons = discover_comparisons(root)
    app = FastAPI(title="Compute Bazaar Evals", docs_url=None, redoc_url=None)
    app.mount("/assets", StaticFiles(directory=ASSET_ROOT), name="assets")

    def refresh_catalog() -> None:
        nonlocal task_definitions, job_sources, comparisons
        task_definitions = discover_task_definitions(root)
        job_sources = discover_job_sources(root, results_source)
        comparisons = discover_comparisons(root)

    def job_source(eval_slug: str, run_id: str) -> JobSource:
        source = job_sources.get(eval_slug, {}).get(run_id)
        if source is None:
            raise HTTPException(status_code=404, detail="run not found")
        return source

    def note_path(source: JobSource) -> Path:
        assert source.notes_dir is not None
        return source.notes_dir

    def presentation(eval_slug: str, run_id: str) -> JobPresentation:
        source = job_source(eval_slug, run_id)
        if source.raw_dir is not None:
            task = task_definitions.get(eval_slug) or TaskInfo(
                slug=eval_slug,
                name=eval_slug.replace("-", " ").title(),
                domain="Evaluation",
            )
            raw = present_harbor_job(source.raw_dir, task, run_id)
            return apply_report_overlay(
                raw,
                source.report_dir,
                eval_slug,
                public_context=source.public_context,
            )
        assert source.report_dir is not None
        return load_job_presentation(source.report_dir, eval_slug, run_id)

    def run_summaries(eval_slug: str) -> list[dict[str, Any]]:
        sources = job_sources.get(eval_slug)
        if sources is None and eval_slug not in task_definitions:
            raise HTTPException(status_code=404, detail="eval not found")
        if not sources:
            return []
        summaries = []
        for run_id, source in sources.items():
            note = _read_note(note_path(source))
            if source.raw_dir is not None and source.report_dir is None:
                raw = summarize_harbor_job(source.raw_dir, eval_slug)
                score = (
                    Metric(
                        label="Mean reward",
                        value=f"{raw.mean_reward:.4f}",
                        hint="Harbor verifier reward averaged across scored trials",
                    )
                    if raw.mean_reward is not None
                    else None
                )
                origin = ""
                if source.public_context:
                    origin = str(source.public_context.get("display_label") or "")
                summary = {
                    "run_id": run_id,
                    "started_at": raw.started_at,
                    "finished_at": raw.finished_at,
                    "started": _format_timestamp(raw.started_at),
                    "score": score,
                    "agents": len(raw.agent_configurations),
                    "trials": raw.trial_count,
                    "note": note["text"],
                    "note_updated_at": note["updated_at"],
                    "origin": origin,
                    "comparable": True,
                }
            else:
                summary = _run_summary(presentation(eval_slug, run_id), note)
                summary["comparable"] = source.raw_dir is not None
            summaries.append((summary, source.modified_at))
        summaries.sort(
            key=lambda item: (
                _timestamp_sort_key(item[0]["started_at"]),
                item[1],
                item[0]["run_id"],
            ),
            reverse=True,
        )
        return [summary for summary, _ in summaries]

    def latest_run_id(eval_slug: str) -> str:
        sources = job_sources.get(eval_slug)
        if not sources:
            raise HTTPException(status_code=404, detail="eval not found")
        return run_summaries(eval_slug)[0]["run_id"]

    def evaluation_summaries() -> list[dict[str, Any]]:
        summaries = []
        for eval_slug in sorted(set(task_definitions) | set(job_sources)):
            sources = job_sources.get(eval_slug, {})
            if sources:
                raw_job_ids = [
                    job_id
                    for job_id, source in sources.items()
                    if source.raw_dir is not None
                ]
                counted_job_ids = raw_job_ids or list(sources)
                agent_configurations: set[tuple[str, str]] = set()
                trial_count = 0
                for job_id in counted_job_ids:
                    source = sources[job_id]
                    if source.raw_dir is not None:
                        raw = summarize_harbor_job(source.raw_dir, eval_slug)
                        agent_configurations.update(raw.agent_configurations)
                        trial_count += raw.trial_count
                    else:
                        job = presentation(eval_slug, job_id)
                        trial_count += job.trial_count
                        agent_configurations.update(
                            (
                                row.cells.get("agent", TableCell(value="")).value,
                                row.cells.get("model", TableCell(value="")).value,
                            )
                            for row in job.agent_table.rows
                            if row.cells.get("agent", TableCell(value="")).value
                        )
                summaries.append(
                    _evaluation_summary(
                        task_info(eval_slug),
                        jobs=len(counted_job_ids),
                        agent_configurations=agent_configurations,
                        trials=trial_count,
                    )
                )
            else:
                summaries.append(_empty_evaluation_summary(task_definitions[eval_slug]))
        return summaries

    def task_info(eval_slug: str) -> TaskInfo:
        task = task_definitions.get(eval_slug)
        if task is not None:
            return task
        sources = job_sources.get(eval_slug, {})
        if sources:
            return presentation(eval_slug, latest_run_id(eval_slug)).task
        raise HTTPException(status_code=404, detail="eval not found")

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        refresh_catalog()
        return _evals_html(evaluation_summaries(), base_path)

    @app.get("/comparisons", response_class=HTMLResponse)
    def comparisons_index() -> str:
        refresh_catalog()
        return _comparisons_index_html(comparison_references(comparisons), base_path)

    @app.get("/comparisons/jobs", response_class=HTMLResponse)
    def compare_jobs(
        task: str,
        job: list[str] = Query(default=[]),
    ) -> str:
        refresh_catalog()
        if len(job) < 2:
            raise HTTPException(status_code=422, detail="select at least two jobs")
        selected = []
        for job_id in dict.fromkeys(job):
            source = job_sources.get(task, {}).get(job_id)
            if source is None:
                raise HTTPException(status_code=404, detail=f"job not found: {job_id}")
            selected.append(source)
        try:
            comparison = build_job_comparison(task_info(task), selected)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _comparison_page_html(comparison, base_path)

    @app.get("/comparisons/{comparison_id}", response_class=HTMLResponse)
    def comparison_detail(comparison_id: str) -> str:
        refresh_catalog()
        comparison = comparisons.get(comparison_id)
        if comparison is None:
            raise HTTPException(status_code=404, detail="comparison not found")
        return _comparison_page_html(comparison, base_path)

    @app.get("/evals/{eval_slug}", response_class=HTMLResponse)
    def evaluation(eval_slug: str) -> str:
        refresh_catalog()
        return _runs_html(
            task_info(eval_slug),
            run_summaries(eval_slug),
            base_path,
            task_comparison_references(comparisons, eval_slug),
        )

    @app.get("/evals/{eval_slug}/jobs/{run_id}", response_class=HTMLResponse)
    def job_detail(eval_slug: str, run_id: str) -> str:
        refresh_catalog()
        return _index_html(
            presentation(eval_slug, run_id),
            _read_note(note_path(job_source(eval_slug, run_id))),
            base_path,
        )

    @app.get(
        "/evals/{eval_slug}/jobs/{run_id}/trials/{trial_name}",
        response_class=HTMLResponse,
    )
    def trial_detail(eval_slug: str, run_id: str, trial_name: str) -> str:
        refresh_catalog()
        job = presentation(eval_slug, run_id)
        match = job.trials.get(trial_name)
        if match is None:
            raise HTTPException(status_code=404, detail="trial not found")
        return _trial_html(match, job, base_path)

    @app.get("/api/evals")
    def evals_api() -> list[dict[str, Any]]:
        refresh_catalog()
        return evaluation_summaries()

    @app.get("/api/comparisons")
    def comparisons_api() -> list[dict[str, Any]]:
        refresh_catalog()
        return [item.model_dump() for item in comparison_references(comparisons)]

    @app.get("/api/comparisons/{comparison_id}")
    def comparison_api(comparison_id: str) -> dict[str, Any]:
        refresh_catalog()
        comparison = comparisons.get(comparison_id)
        if comparison is None:
            raise HTTPException(status_code=404, detail="comparison not found")
        return comparison.model_dump()

    @app.get("/api/evals/{eval_slug}/jobs")
    def runs_api(eval_slug: str) -> list[dict[str, Any]]:
        refresh_catalog()
        return run_summaries(eval_slug)

    @app.get("/api/evals/{eval_slug}/jobs/{run_id}")
    def run_api(eval_slug: str, run_id: str) -> dict[str, Any]:
        refresh_catalog()
        return presentation(eval_slug, run_id).model_dump()

    @app.post("/api/evals/{eval_slug}/jobs/{run_id}/note")
    def save_job_note(eval_slug: str, run_id: str, note: JobNote) -> dict[str, str]:
        refresh_catalog()
        return _write_note(note_path(job_source(eval_slug, run_id)), note.text)

    @app.get("/api/evals/{eval_slug}/jobs/{run_id}/trials")
    def run_trials_api(eval_slug: str, run_id: str) -> list[dict[str, Any]]:
        refresh_catalog()
        return [
            trial.model_dump()
            for trial in presentation(eval_slug, run_id).trials.values()
        ]

    @app.get("/api/protocol")
    def protocol_api() -> dict[str, Any]:
        refresh_catalog()
        if not job_sources:
            raise HTTPException(status_code=404, detail="no jobs found")
        eval_slug = next(iter(job_sources))
        return presentation(eval_slug, latest_run_id(eval_slug)).model_dump()

    @app.get("/api/trials")
    def trials_api() -> list[dict[str, Any]]:
        refresh_catalog()
        if not job_sources:
            raise HTTPException(status_code=404, detail="no jobs found")
        eval_slug = next(iter(job_sources))
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
