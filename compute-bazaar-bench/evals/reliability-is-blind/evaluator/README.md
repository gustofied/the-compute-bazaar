# Evaluator

These tools sit around the Harbor task. They never change task reward or raw
job history.

## Files

- `protocol.py`: prepares and runs a precommitted matched-seed model matrix.
- `analysis.py`: reads Harbor configs, ATIF, protected ledgers, artifacts, and
  verifier outputs into deterministic trial and protocol reports.
- `view.py`: compatibility launcher for the shared FastAPI viewer in
  `compute-bazaar-bench/viewer/`.
- `reliability_is_blind/engine.py`: canonical development copy of the frozen
  market engine, byte-matched to the task sidecar and verifier copies.

## Analyze

```bash
uv run python compute-bazaar-bench/evals/reliability-is-blind/evaluator/protocol.py analyze \
  --manifest .secrets/reliability-is-blind-mistral-matched-20.json \
  --commitment compute-bazaar-bench/evals/reliability-is-blind/protocols/reliability-is-blind-mistral-matched-20.commitment.json \
  --jobs-dir compute-bazaar-bench/jobs/raw \
  --phase full \
  --output compute-bazaar-bench/jobs/reports/reliability-is-blind/runs/reliability-is-blind-mistral-matched-20
```

## View

```bash
uv run python compute-bazaar-bench/evals/reliability-is-blind/evaluator/view.py \
  compute-bazaar-bench/jobs/reports \
  --port 8084
```

The preferred shared launcher is:

```bash
uv run python compute-bazaar-bench/viewer/app.py \
  compute-bazaar-bench/jobs/reports \
  --port 8084
```

Normalized viewer reports are stored under
`compute-bazaar-bench/jobs/reports/<task>/runs/<job>/`. The Reliability Is
Blind presenter maps its protocol analysis into the generic viewer contract;
other evaluations can use their own presenter or write `view.json` directly.

The generated analysis contains private seed strata and hidden supplier
diagnostics. Bind the viewer only to localhost and do not publish those files.
