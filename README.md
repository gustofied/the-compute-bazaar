# The Compute Bazaar

Artefacts from tinkering with compute markets.

## Setup

This is a `uv` project. Install the locked environment with:

```sh
uv sync
```

Run scripts through the project entry points:

```sh
uv run ireland-compute-map
uv run ie-dc-share
uv run download-eirgrid --start 2026-01-01 --end 2026-01-31 --out eirgrid_demand.csv
uv run ie-dc-consumption --file eirgrid_demand.csv --plot ireland_consumption.png
uv run ie-flow-map --file /path/to/System-Data-Qtr-Hourly.xlsx --out ie_flow_map.png
uv run openalex-papers --query "GPU-hours" --out data/papers/openalex_candidates.csv
```

Scripts that consume EirGrid Excel exports require `--file /path/to/export.xlsx`.

## Paper Compute Search

Find candidate papers that may report AI training compute:

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

The CSV and HTML are intentionally candidate lists, not verified datasets. The
review schema includes model name, organization, model size, training tokens,
dataset size, accelerator, GPU count, duration, GPU-hours, FLOPs, reported cost,
estimated cost, compute type, evidence quote, confidence, and notes. Use the
HTML review dashboard for marking papers, exploring D3 charts, and drafting the
working article thesis. Use `--include-abstract` if you want full abstracts in
the CSV; JSONL always keeps them.

Open the HTML file in a browser for a searchable, clickable review table. You
can also render a table from an existing CSV without calling OpenAlex again:

```sh
uv run openalex-papers \
  --from-csv data/papers/openalex_candidates.csv \
  --html data/papers/openalex_candidates.html
```

## GPU Price Platform

The market-data path is designed around:

```text
Provider APIs -> AutoMQ events -> S3 raw evidence -> Parquet lake -> DataFusion SQL
```

Windmill can call the package entry points for schedules, manual runs, approvals, and agent workflows.

Ingest Vast offers:

```sh
export VAST_API_KEY=...
export AUTOMQ_BOOTSTRAP_SERVERS=localhost:9092

uv run gpu-prices ingest-vast \
  --raw-root s3://compute-bazaar/raw \
  --lake-root s3://compute-bazaar/lake
```

For a local dry run without AutoMQ:

```sh
uv run gpu-prices ingest-vast --dry-run --raw-root data/raw --lake-root data/lake
```

Run a benchmark query over normalized Parquet:

```sh
uv run gpu-prices benchmark --parquet data/lake/silver/gpu_offers/date=YYYY-MM-DD/provider=vast/run_id=RUN/offers.parquet
```
