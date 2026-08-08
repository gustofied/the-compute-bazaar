# Evaluator

These tools sit around the Harbor task. They never change task reward or raw
job history.

## Files

- `protocol.py`: prepares and runs a precommitted matched-seed model matrix.
- `analysis.py`: reads Harbor configs, ATIF, protected ledgers, artifacts, and
  verifier outputs into deterministic trial and protocol reports.
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
compute-bazaar terminal
```

Normalized reports are stored under
`compute-bazaar-bench/jobs/reports/<task>/runs/<job>/`. Choose **Eval** in the
terminal to open the full task, job, agent, trial, note, and diagnostic viewer.

The generated analysis contains private seed strata and hidden supplier
diagnostics. The Terminal binds to localhost; do not publish those files.
