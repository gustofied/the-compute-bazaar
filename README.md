# The Compute Bazaar

The Compute Bazaar is a Stage 1 GPU market-data platform. It ingests provider
data, preserves raw evidence in S3, normalizes offers into a common schema,
builds gold query tables for price indexes and provider comparisons, and exposes
the results through DataFusion, CLI commands, dashboard snapshots, and later
API/MCP tools for agents.

## Architecture

```text
Provider APIs
  -> Windmill scheduled workers
  -> AutoMQ / Kafka event stream
  -> S3 bronze raw evidence
  -> S3 silver normalized offers
  -> S3 gold query/index tables
  -> DataFusion SQL
  -> dashboard / CLI / future API / agents
```

Layer roles:

```text
bronze/raw evidence        exact provider responses for audit and replay
silver/gpu_offers          normalized provider offers in one schema
gold/fact_gpu_listings     query-ready market listings
gold/fact_price_index_*    index values and constituents
gold/dim_*                 GPU, provider, and region dimensions
AutoMQ                     live event tape
DataFusion                 SQL over lake tables
dashboard                  first product surface
```

See [docs/architecture.md](docs/architecture.md) for the platform model and
[docs/stage1-review.md](docs/stage1-review.md) for the current review boundary.
See [docs/public-dashboard.md](docs/public-dashboard.md) for the public S3/CloudFront
dashboard path.

## Setup

This is a `uv` project.

```sh
uv sync
uv run python -m unittest discover -s tests
```

Real secrets belong in `.env`, `.secrets/`, or Windmill secrets only. The public
`.env.example` shows variable names without credentials.

## Environment

For provider ingestion and S3 lake writes:

```sh
export VAST_API_KEY=...
export LIUM_API_KEY=...
export COMPUTE_BAZAAR_RAW_ROOT=s3://YOUR_BUCKET/raw
export COMPUTE_BAZAAR_LAKE_ROOT=s3://YOUR_BUCKET/lake
export COMPUTE_BAZAAR_DASHBOARD_OUTPUT_ROOT=s3://YOUR_BUCKET/dashboard/compute-bazaar
export AWS_PROFILE=compute-bazaar
export AWS_REGION=YOUR_AWS_REGION
```

For AutoMQ/Kafka publishing:

```sh
export COMPUTE_BAZAAR_KAFKA_BOOTSTRAP_SERVERS=...
export COMPUTE_BAZAAR_KAFKA_SECURITY_PROTOCOL=SASL_PLAINTEXT
export COMPUTE_BAZAAR_KAFKA_SASL_MECHANISM=SCRAM-SHA-256
export COMPUTE_BAZAAR_KAFKA_USERNAME=...
export COMPUTE_BAZAAR_KAFKA_PASSWORD=...
```

AutoMQ brokers use private VPC DNS, so Kafka-producing jobs should run from the
VPC-connected Windmill worker. Laptop runs can use `--dry-run`.

## Ingest Providers

Local dry runs:

```sh
uv run gpu-prices ingest-vast --dry-run --raw-root data/raw --lake-root data/lake
uv run gpu-prices ingest-lium --dry-run --paginate --max-pages 10 --raw-root data/raw --lake-root data/lake
```

VPC/Windmill production-shaped runs publish to AutoMQ and write S3:

```sh
uv run gpu-prices ingest-vast
uv run gpu-prices ingest-lium --size 200 --paginate --max-pages 10
```

Inspect latest provider output:

```sh
uv run gpu-prices latest-manifest --provider vast
uv run gpu-prices latest-manifest --provider lium
uv run gpu-prices latest-index --provider vast --limit 10
```

Windmill setup lives in [infra/windmill/](infra/windmill/).

## Market Heartbeat

The main Stage 1.5 loop is `market-hourly`. It ingests both providers, writes bronze/silver,
builds gold, exports dashboard JSON, and writes one top-level market run manifest.

```sh
uv run gpu-prices market-hourly --dry-run \
  --raw-root data/raw \
  --lake-root data/lake \
  --dashboard-output-root data/dashboard/compute-bazaar

uv run gpu-prices latest-market-run
uv run gpu-prices market-runs --limit 12
```

In Windmill, bootstrap the same loop with:

```sh
export WINDMILL_TOKEN=...
export WINDMILL_WORKSPACE=compute-bazaar
uv run python infra/windmill/bootstrap_market_schedule.py
```

The private lake manifest keeps provider raw refs and silver refs for audit. The dashboard export
keeps only public-safe status, counts, and query rows.

## Build Gold

Build combined gold tables from latest provider silver manifests:

```sh
uv run gpu-prices build-gold --providers vast,lium
uv run gpu-prices latest-gold-manifest
uv run gpu-prices gold-index --limit 10
uv run gpu-prices gold-index-quality --limit 20
uv run gpu-prices gold-index-constituents --limit 50
uv run gpu-prices gold-provider-comparison --limit 20
uv run gpu-prices export-gold-dashboard --limit 100
```

The provider comparison and price-index commands filter to available offers.
The listing table keeps broader evidence rows so provider state can be inspected
without polluting market-floor outputs.
The constituents table keeps included and excluded index candidates with an
`exclusion_reason`, so index values can be explained rather than only displayed.

## Dashboard

The first local product surface is:

```text
prototypes/compute-bazaar/feeling_the_compute.html
```

It follows the AdamSioud exemplar flow and reads public-safe gold snapshots from
the local FastAPI snapshot API. By default that API reads S3 when
`COMPUTE_BAZAAR_DASHBOARD_SOURCE=s3` and `COMPUTE_BAZAAR_DASHBOARD_S3_PREFIX`
are set, otherwise it falls back to `data/dashboard/compute-bazaar/`.

Run the local FastAPI dashboard:

```sh
uv run compute-bazaar-dashboard
```

Then open:

```text
http://127.0.0.1:8765/
```

Useful endpoints:

```text
/dashboard/
/api/health
/api/snapshots
/api/dashboard-snapshots/manifest.json
/api/dashboard-snapshots/latest-index.json
/api/snapshots/latest-index
/api/snapshots/market-history
/api/snapshots/index-quality
/api/snapshots/index-constituents
```

The page auto-refreshes its JSON data every five minutes by default. Disable or tune that with:

```text
?refresh=0
?refreshMs=60000
```

The same page can later point at public S3/CloudFront JSON directly with:

```text
?data=https://YOUR_PUBLIC_HOST/compute-bazaar
```

## Website Submodule

The AdamSioud website repo is attached as a private submodule at:

```text
external/AdamSioud
```

This lets us work against the real website page without vendoring the site into
this project. The useful target is:

```text
external/AdamSioud/exemplars/compute/feeling_the_compute.html
```

The local checkout is sparse around the Compute exemplar and shared site files.
For a fresh clone:

```sh
git submodule update --init --depth 1 --filter=blob:none external/AdamSioud
git -C external/AdamSioud sparse-checkout set \
  CNAME README.md edit.js exemplars/compute exemplars/images index.html script.js style.css tendrils.js
```

Run the publication-shaped local site:

```sh
uv run compute-bazaar-adamsioud
```

Then open the local equivalent of the public URL:

```text
http://127.0.0.1:8777/exemplars/compute/feeling_the_compute.html
```

That server also exposes `/api/dashboard-snapshots/*.json`, so the AdamSioud page can keep its
static-site shape while syncing small public-safe labels from the latest S3 gold snapshot. The first
label is `gold avg floor`, calculated from `latest-index.json` product floor values. The prototype
dashboard remains the draft surface; AdamSioud should receive only composed, publication-ready
signals.

## Stage Check

From a laptop with the Windmill SSH tunnel:

```sh
WINDMILL_BASE_URL=http://127.0.0.1:8081 \
  uv run gpu-prices stage1-check --provider vast
```

From the VPC worker, add the private Kafka check:

```sh
gpu-prices stage1-check --check-automq --require-ingest-env
```

## Current Limitations

- `market_hourly` is now the main loop and has run from the VPC Windmill worker. Keep watching
  the hourly runs before we call it boring.
- Lium ingestion paginates and dedupes by default in the Windmill path, but the provider API shape
  should still be observed over real runs before we assume complete-market coverage.
- The dev Windmill worker is a baked EC2 Docker image. Tighten this with a
  registry-built worker image, narrower IAM, and production Windmill sandboxing
  before exposing it beyond the current private setup.
- Public dashboard JSON has a documented S3/CloudFront path, but the distribution/CORS setup still
  needs to be applied before the AdamSioud blog page can fetch it directly.
