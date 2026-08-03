# Evaluator

These tools sit around the Harbor task. They never change task reward or raw
job history.

## Files

- `protocol.py`: prepares and runs a precommitted matched-seed model matrix.
- `analysis.py`: reads Harbor configs, ATIF, protected ledgers, artifacts, and
  verifier outputs into deterministic trial and protocol reports.
- `view.py`: serves the generated report as a private localhost FastAPI view.
- `reliability_is_blind/engine.py`: canonical development copy of the frozen
  market engine, byte-matched to the task sidecar and verifier copies.

## Analyze

```bash
uv run python evals/reliability-is-blind/evaluator/protocol.py analyze \
  --manifest .secrets/reliability-is-blind-mistral-matched-20.json \
  --commitment evals/reliability-is-blind/protocols/reliability-is-blind-mistral-matched-20.commitment.json \
  --jobs-dir evals/jobs \
  --phase full
```

## View

```bash
uv run python evals/reliability-is-blind/evaluator/view.py \
  evals/jobs/reliability-is-blind-mistral-matched-20-analysis-full \
  --port 8084
```

The generated analysis contains private seed strata and hidden supplier
diagnostics. Bind the viewer only to localhost and do not publish those files.
