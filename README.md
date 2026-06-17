# The Compute Bazaar

Artefacts from tinkering with compute markets.

## Setup

This is a `uv` project. Install the locked environment with:

```sh
uv sync
```

Run the focused test suite with:

```sh
uv run python -m unittest discover -s tests
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
Provider APIs -> AutoMQ events -> S3 bronze/silver/gold lake -> DataFusion SQL
```

Windmill can call the package entry points for schedules, manual runs, approvals, and agent workflows.
The current Windmill worker setup lives in `infra/windmill/`; run the worker inside the AWS VPC
because the AutoMQ endpoint is private DNS.

Keep real secrets in `.env`, `.secrets/`, or Windmill secrets only. The public `.env.example`
shows variable names without shipping credentials.

Ingest Vast offers:

```sh
export VAST_API_KEY=...
export LIUM_API_KEY=...
export COMPUTE_BAZAAR_KAFKA_BOOTSTRAP_SERVERS=localhost:9092
export COMPUTE_BAZAAR_KAFKA_SECURITY_PROTOCOL=SASL_PLAINTEXT
export COMPUTE_BAZAAR_KAFKA_SASL_MECHANISM=SCRAM-SHA-256
export COMPUTE_BAZAAR_KAFKA_USERNAME=...
export COMPUTE_BAZAAR_KAFKA_PASSWORD=...
export AWS_PROFILE=compute-bazaar
export AWS_REGION=YOUR_AWS_REGION

uv run gpu-prices ingest-vast \
  --raw-root s3://YOUR_BUCKET/raw \
  --lake-root s3://YOUR_BUCKET/lake
```

Ingest Lium executors:

```sh
uv run gpu-prices ingest-lium --size 200
```

For a local dry run without AutoMQ or S3:

```sh
uv run gpu-prices ingest-vast --dry-run --raw-root data/raw --lake-root data/lake
uv run gpu-prices ingest-lium --dry-run --raw-root data/raw --lake-root data/lake
```

Inspect the latest successful run and compute a first price index:

```sh
uv run gpu-prices latest-manifest
uv run gpu-prices latest-index --limit 10
```

Build the first gold query tables from latest silver offers:

```sh
uv run gpu-prices build-gold
uv run gpu-prices build-gold --providers vast,lium
uv run gpu-prices latest-gold-manifest
uv run gpu-prices gold-index --limit 10
uv run gpu-prices gold-provider-comparison --limit 20
uv run gpu-prices export-gold-dashboard --limit 100
```

The provider comparison and price-index commands filter to available offers. The listing table keeps
the broader evidence rows so we can inspect provider state without polluting market-floor outputs.

The lake layers are:

```text
bronze/raw evidence        exact provider responses for audit and replay
silver/gpu_offers          normalized provider offers in one schema
gold/fact_gpu_listings     query-ready market listings
gold/fact_price_index_*    index values and constituents
gold/dim_*                 GPU, provider, and region dimensions
```

`export-gold-dashboard` writes public-safe JSON snapshots under `data/dashboard/compute-bazaar/`.
Those files are intended for D3 prototypes in the static Compute Bazaar essay before we add a
proper API or live feed.

The first static essay prototype lives at:

```text
prototypes/compute-bazaar/feeling_the_compute.html
```

Treat that page as the primary local dashboard/interface for the project while the market is still
forming. It follows the AdamSioud exemplar flow, but reads the local Compute Bazaar gold snapshots.

Serve the repository root locally and open that page so browser `fetch()` can read the JSON files:

```sh
uv run compute-bazaar-dashboard
```

Then open `http://127.0.0.1:8765/`. The FastAPI server also exposes:

```text
/dashboard/
/api/health
/api/snapshots
/api/snapshots/latest-index
```

The same page can point at S3/CloudFront JSON later with
`?data=https://YOUR_PUBLIC_HOST/compute-bazaar`.

Run the Stage 1 check from your laptop. This checks the latest S3 manifest, DataFusion index,
and Windmill schedule when `WINDMILL_BASE_URL` points at an SSH tunnel:

```sh
WINDMILL_BASE_URL=http://127.0.0.1:8081 uv run gpu-prices stage1-check
```

AutoMQ brokers use private VPC DNS, so the Kafka connectivity check must run from a VPC-connected
host or worker:

```sh
gpu-prices stage1-check --check-automq --require-ingest-env
```
