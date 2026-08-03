"""Local FastAPI viewer for Reliability Is Blind protocol analysis."""

from __future__ import annotations

import argparse
from html import escape
import json
from pathlib import Path
from typing import Any, Sequence

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
import uvicorn


STYLE = """
:root {
  color-scheme: dark;
  --bg: #090909;
  --panel: #111111;
  --line: #2b2b2b;
  --line-strong: #454545;
  --text: #f2f2f2;
  --muted: #9b9b9b;
  --green: #64d98b;
  --amber: #efbd5b;
  --red: #ef7474;
  --blue: #73a9ff;
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
.shell { width: min(1480px, calc(100% - 32px)); margin: 0 auto; padding: 28px 0 56px; }
header { display: flex; justify-content: space-between; gap: 24px; align-items: flex-start; margin-bottom: 24px; }
h1 { margin: 0 0 8px; font-size: 26px; line-height: 1.15; letter-spacing: 0; }
h2 { margin: 0; font-size: 15px; letter-spacing: 0; }
.eyebrow, .muted { color: var(--muted); }
.eyebrow { font-size: 12px; margin-bottom: 8px; text-transform: uppercase; }
.status { border: 1px solid var(--line-strong); padding: 7px 9px; border-radius: 4px; white-space: nowrap; }
.status.good { color: var(--green); border-color: #316d45; }
.status.warn { color: var(--amber); border-color: #745a2b; }
.notice { border: 1px solid #624e27; color: var(--amber); padding: 10px 12px; margin: 0 0 20px; }
.metrics { display: grid; grid-template-columns: repeat(6, minmax(130px, 1fr)); border: 1px solid var(--line); margin-bottom: 24px; }
.metric { min-height: 92px; padding: 14px; border-right: 1px solid var(--line); }
.metric:last-child { border-right: 0; }
.metric-label { color: var(--muted); font-size: 11px; text-transform: uppercase; }
.metric-value { font-size: 24px; margin-top: 12px; line-height: 1; }
.section { margin-top: 26px; }
.section-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; gap: 16px; }
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
th { color: var(--muted); font-size: 11px; text-transform: uppercase; background: #0d0d0d; position: sticky; top: 0; }
tr:last-child td { border-bottom: 0; }
tbody tr:hover { background: #151515; }
.num { text-align: right; font-variant-numeric: tabular-nums; }
.good { color: var(--green); }
.warn { color: var(--amber); }
.bad { color: var(--red); }
.info { color: var(--blue); }
.tag { display: inline-block; border: 1px solid var(--line-strong); border-radius: 3px; padding: 3px 5px; font-size: 11px; }
.detail-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); border: 1px solid var(--line); }
.detail { padding: 14px; border-right: 1px solid var(--line); border-bottom: 1px solid var(--line); }
.detail:nth-child(2n) { border-right: 0; }
.detail-key { color: var(--muted); font-size: 11px; text-transform: uppercase; margin-bottom: 7px; }
pre { overflow: auto; background: #0d0d0d; border: 1px solid var(--line); padding: 14px; line-height: 1.45; }
.back { display: inline-block; margin-bottom: 20px; color: var(--muted); }
@media (max-width: 980px) {
  .metrics { grid-template-columns: repeat(3, 1fr); }
  .metric:nth-child(3) { border-right: 0; }
  .metric:nth-child(-n+3) { border-bottom: 1px solid var(--line); }
}
@media (max-width: 640px) {
  .shell { width: min(100% - 20px, 1480px); padding-top: 18px; }
  header, .section-head { flex-direction: column; }
  .metrics { grid-template-columns: repeat(2, 1fr); }
  .metric:nth-child(3) { border-right: 1px solid var(--line); }
  .metric:nth-child(2n) { border-right: 0; }
  .metric:nth-child(-n+4) { border-bottom: 1px solid var(--line); }
  .detail-grid { grid-template-columns: 1fr; }
  .detail { border-right: 0; }
}
"""


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot read analysis file {path}: {exc}") from exc


def _fmt(value: Any, digits: int = 3) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _pct(value: Any) -> str:
    return "—" if value is None else f"{100 * float(value):.1f}%"


def _class_for_outcome(value: str) -> str:
    if value == "completed":
        return "good"
    if value in {"interface_failure", "action_control_failure"}:
        return "bad"
    return "warn"


def _layout(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)}</title><style>{STYLE}</style></head><body><main class="shell">{body}</main></body></html>"""


def _index_html(protocol: dict[str, Any]) -> str:
    ranking = bool(protocol.get("ranking_allowed"))
    gate = bool(protocol.get("canary_gate_passed"))
    status_class = "good" if ranking or gate else "warn"
    model_rows = "".join(
        f"""<tr><td>{escape(model["model"])}</td>
<td class="num">{model["observed_trials"]}/{model["planned_trials"]}</td>
<td class="num">{model["completed_rollouts"]}</td>
<td class="num">{model["reliability_targets_met"]}</td>
<td class="num">{model["attribution_challenges_activated"]}</td>
<td class="num">{_fmt(model["mean_reward"], 4)}</td>
<td class="num">{_pct(model["mean_completed_failure_rate"])}</td>
<td class="num">{model["invalid_selections"]}</td>
<td class="num">{_fmt(model["reported_cost_usd"], 4)} <span class="muted">{escape(model["cost_coverage"])}</span></td></tr>"""
        for model in protocol.get("models", [])
    )
    trial_rows = "".join(
        f"""<tr data-search="{escape(" ".join(str(value) for value in trial.values()).lower())}">
<td><a class="info" href="/trials/{escape(trial["name"])}">{escape(trial["cell_id"])}</a></td>
<td>{escape(trial["model"].split("/")[-1])}</td>
<td><span class="tag {_class_for_outcome(trial["control_outcome"])}">{escape(trial["control_outcome"])}</span></td>
<td>{escape(trial["highest_layer_reached"])}</td>
<td class="num">{trial["completed_deals"]}</td><td class="num">{trial["failed_deals"]}</td>
<td class="num">{_pct(trial["failure_rate"])}</td><td class="num">{_fmt(trial["reward"], 4)}</td>
<td class="num">{"yes" if trial["attribution_challenge_activated"] else "no"}</td>
<td class="num">{trial["invalid_selections"]}</td></tr>"""
        for trial in protocol.get("trials", [])
    )
    issues = ""
    if protocol.get("issues"):
        issues = (
            '<div class="notice">'
            + "<br>".join(escape(issue) for issue in protocol["issues"][:8])
            + "</div>"
        )
    body = f"""
<header><div><div class="eyebrow">Compute Bazaar / evaluator view</div><h1>Reliability Is Blind</h1><div class="muted">{escape(protocol.get("protocol_id", ""))}</div></div>
<div class="status {status_class}">{escape(protocol.get("label", ""))}</div></header>
<div class="notice">Private evaluator view. Hidden seed strata and supplier diagnostics are not agent-visible.</div>{issues}
<section class="metrics">
<div class="metric"><div class="metric-label">Observed trials</div><div class="metric-value">{protocol.get("observed_trials", 0)}/{protocol.get("planned_trials", 0)}</div></div>
<div class="metric"><div class="metric-label">Matched seeds</div><div class="metric-value">{protocol.get("matched_seed_cells", 0)}/{protocol.get("planned_seed_cells", 0)}</div></div>
<div class="metric"><div class="metric-label">Completed books</div><div class="metric-value">{protocol.get("completed_rollouts", 0)}</div></div>
<div class="metric"><div class="metric-label">Target met</div><div class="metric-value">{protocol.get("reliability_targets_met", 0)}</div></div>
<div class="metric"><div class="metric-label">Attribution activated</div><div class="metric-value">{protocol.get("attribution_challenges_activated", 0)}</div></div>
<div class="metric"><div class="metric-label">Errors / open / retries</div><div class="metric-value">{protocol.get("job_error_count", 0)} / {protocol.get("job_unfinished_count", 0)} / {protocol.get("job_retry_count", 0)}</div></div>
</section>
<section class="section"><div class="section-head"><h2>Models</h2><span class="muted">Reward is exact; activation is diagnostic.</span></div>
<div class="table-wrap"><table><thead><tr><th>Model</th><th class="num">Observed</th><th class="num">Complete</th><th class="num">Target</th><th class="num">Activated</th><th class="num">Mean reward</th><th class="num">Failure rate</th><th class="num">Invalid</th><th class="num">Reported cost</th></tr></thead><tbody>{model_rows}</tbody></table></div></section>
<section class="section"><div class="section-head"><h2>Trials</h2><input id="search" aria-label="Filter trials" placeholder="Filter model, cell, outcome or layer"></div>
<div class="table-wrap"><table><thead><tr><th>Seed cell</th><th>Model</th><th>Control</th><th>Capability layer</th><th class="num">Deals</th><th class="num">Failed</th><th class="num">Failure rate</th><th class="num">Reward</th><th class="num">Activated</th><th class="num">Invalid</th></tr></thead><tbody id="trials">{trial_rows}</tbody></table></div></section>
<script>const q=document.getElementById('search');q.addEventListener('input',()=>{{const v=q.value.toLowerCase();document.querySelectorAll('#trials tr').forEach(r=>r.hidden=!r.dataset.search.includes(v));}});</script>"""
    return _layout("Reliability Is Blind", body)


def _trial_html(trial: dict[str, Any]) -> str:
    summary = {
        "Model": trial["trial"].get("model"),
        "Agent": f"{trial['trial'].get('agent')} {trial['trial'].get('agent_version') or ''}".strip(),
        "Seed cell": trial.get("protocol", {}).get("cell_id"),
        "Control outcome": trial["control"].get("outcome"),
        "Capability layer": trial["capability"].get("highest_layer_reached"),
        "Completed deals": trial["control"].get("completed_deals"),
        "Failed deals": trial["result"].get("failed_deals"),
        "Reward": _fmt(trial["result"].get("reward"), 4),
        "Attribution activated": trial["capability"].get(
            "attribution_challenge_activated"
        ),
        "Distinct bundles": trial["policy"].get("distinct_bundles"),
        "Top bundle share": _pct(trial["policy"].get("top_bundle_share")),
        "Invalid selections": trial["control"].get("invalid_selections"),
    }
    details = "".join(
        f'<div class="detail"><div class="detail-key">{escape(str(key))}</div><div>{escape(str(value))}</div></div>'
        for key, value in summary.items()
    )
    body = f"""<a class="back" href="/">← All trials</a><header><div><div class="eyebrow">Private trial analysis</div><h1>{escape(trial["trial"]["name"])}</h1></div></header>
<div class="detail-grid">{details}</div>
<section class="section"><div class="section-head"><h2>Control</h2></div><pre>{escape(json.dumps(trial["control"], indent=2, sort_keys=True))}</pre></section>
<section class="section"><div class="section-head"><h2>Policy</h2></div><pre>{escape(json.dumps(trial["policy"], indent=2, sort_keys=True))}</pre></section>
<section class="section"><div class="section-head"><h2>Capability activation</h2></div><pre>{escape(json.dumps(trial["capability"], indent=2, sort_keys=True))}</pre></section>
<section class="section"><div class="section-head"><h2>Hidden evaluator diagnostics</h2><span class="warn">Never agent-visible</span></div><pre>{escape(json.dumps(trial["hidden_diagnostics"], indent=2, sort_keys=True))}</pre></section>"""
    return _layout(str(trial["trial"]["name"]), body)


def create_app(analysis_dir: Path) -> FastAPI:
    analysis_dir = analysis_dir.resolve()
    protocol_path = analysis_dir / "protocol.json"
    trials_path = analysis_dir / "trials.json"
    if not protocol_path.exists() or not trials_path.exists():
        raise RuntimeError(
            "analysis directory must contain protocol.json and trials.json"
        )
    app = FastAPI(
        title="Reliability Is Blind Evaluator View", docs_url=None, redoc_url=None
    )

    def protocol() -> dict[str, Any]:
        value = _read_json(protocol_path)
        if not isinstance(value, dict):
            raise RuntimeError("protocol analysis must be a JSON object")
        return value

    def trials() -> list[dict[str, Any]]:
        value = _read_json(trials_path)
        if not isinstance(value, list):
            raise RuntimeError("trial analysis must be a JSON list")
        return value

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return _index_html(protocol())

    @app.get("/trials/{trial_name}", response_class=HTMLResponse)
    def trial_detail(trial_name: str) -> str:
        match = next(
            (
                trial
                for trial in trials()
                if trial.get("trial", {}).get("name") == trial_name
            ),
            None,
        )
        if match is None:
            raise HTTPException(status_code=404, detail="trial not found")
        return _trial_html(match)

    @app.get("/api/protocol")
    def protocol_api() -> dict[str, Any]:
        return protocol()

    @app.get("/api/trials")
    def trials_api() -> list[dict[str, Any]]:
        return trials()

    return app


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rib-view")
    parser.add_argument("analysis_directory", type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8084)
    args = parser.parse_args(argv)
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        parser.error("private evaluator data may only bind to localhost")
    uvicorn.run(create_app(args.analysis_directory), host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
