# Paper Compute Search

This is side research tooling for finding candidate papers that may report AI training compute.
It is separate from the GPU price platform.

## Search Candidates

```sh
export OPENALEX_API_KEY=...
export OPENALEX_MAILTO=you@example.com

uv run openalex-papers \
  --query "GPU-hours" \
  --query "pretraining tokens GPU hours" \
  --query "training cost" \
  --query "compute budget" \
  --from-date 2023-01-01 \
  --to-date 2026-12-31 \
  --max-per-query 100 \
  --out data/papers/openalex_candidates.csv \
  --html data/papers/openalex_candidates.html \
  --jsonl data/papers/openalex_candidates.jsonl
```

The CSV and HTML are intentionally candidate lists, not verified datasets. The review schema
includes model name, organization, model size, training tokens, dataset size, accelerator, GPU
count, duration, GPU-hours, FLOPs, reported cost, estimated cost, compute type, evidence quote,
confidence, and notes.

Use the HTML review dashboard for marking papers, exploring D3 charts, and drafting an article
thesis. Use `--include-abstract` if you want full abstracts in the CSV; JSONL always keeps them.

## Render Existing CSV

Open the HTML file in a browser for a searchable, clickable review table. You can also render a
table from an existing CSV without calling OpenAlex again:

```sh
uv run openalex-papers \
  --from-csv data/papers/openalex_candidates.csv \
  --html data/papers/openalex_candidates.html
```
