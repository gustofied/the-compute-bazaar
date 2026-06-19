# Compute Bazaar Architecture

The platform is a GPU market-data system: provider APIs are sampled, raw evidence is retained,
offers are normalized, and curated query/index tables are exposed through DataFusion.

```mermaid
flowchart LR
  Vast["Provider API: Vast.ai"] --> Windmill["Windmill scheduled workers"]
  Lium["Provider API: Lium"] --> Windmill

  Windmill --> AutoMQ["AutoMQ / Kafka topics"]
  Windmill --> Bronze["S3 bronze: raw JSON evidence"]
  Windmill --> Silver["S3 silver: normalized provider offers"]
  Windmill --> MarketRun["S3 manifest: market run heartbeat"]

  Silver --> Gold["S3 gold: curated query/index tables"]
  Gold --> DataFusion["DataFusion SQL"]
  Silver --> DataFusion

  DataFusion --> CLI["CLI queries"]
  DataFusion --> API["Future API / MCP"]
  DataFusion --> Dashboard["D3 blog/dashboard"]
  MarketRun --> Dashboard
  MarketRun --> API
  AutoMQ --> Live["Future live backend / live feed"]
```

## Lake Layers

Bronze is raw evidence. It stores exact provider responses so every derived price can be audited
or replayed.

Silver is normalized provider data. The first silver table is `silver/gpu_offers`, with a common
schema across providers: provider, source offer ID, GPU model, GPU count, price, location,
availability, observation time, and raw reference.

Gold is the query layer. Gold tables are curated models for comparisons, dashboards, APIs, CLI
queries, agents, and index calculations:

- `gold.fact_gpu_listings`
- `gold.fact_price_index_values`
- `gold.fact_index_constituents`
- `gold.dim_gpu_products`
- `gold.dim_providers`
- `gold.dim_regions`

Consumers should mostly read gold. Silver remains useful for debugging, source-level inspection,
and rebuilding gold when the methodology changes.

## Compute Index

The compute index is a first-class gold product, not just an ad hoc query result.

```text
silver/gpu_offers
  -> gold/fact_gpu_listings
  -> index engine
  -> gold/fact_price_index_values
  -> gold/fact_price_index_constituents
```

For Stage 1, the index should stay simple and honest:

```text
Compute Bazaar Live Price Index
Indicative, provider-observed, refreshed hourly
```

The table `gold.fact_price_index_values` should answer questions like:

- What is the market price for H100 right now?
- Was it based on Vast, Lium, or both?
- Is the value a floor, median, p25, or p75?
- What methodology version created it?

The table `gold.fact_price_index_constituents` keeps candidate rows behind each value:

```text
index_value_id
listing_id
provider_id
gpu_product_id
price_per_gpu_hour
included
exclusion_reason
source_run_id
raw_uri
normalization_version
methodology_version
```

Rows with `included = false` are not part of the published floor/index value. Their
`exclusion_reason` records why, such as `not_available` or `non_positive_price`.

That makes the index auditable. Every product output should be traceable back to the raw provider
evidence and the methodology that produced it.

## Current Stage

Stage 1 is live:

- Windmill pulls Vast and Lium from inside the AWS VPC.
- Raw provider responses are written to S3 bronze. Lium stores a raw pagination envelope so the
  bronze layer contains page-level provider evidence, not just extracted rows.
- Normalized offers are written to S3 silver.
- AutoMQ receives provider snapshot and normalized offer events.
- DataFusion can query the latest silver manifest and Parquet file.

Stage 1.5 is now started:

- `gpu-prices build-gold` builds the first gold tables from latest silver.
- `gpu-prices gold-index` queries `gold.fact_price_index_values`.
- `gpu-prices gold-index-quality` summarizes included/excluded candidate counts.
- `gpu-prices gold-index-constituents` exposes index evidence rows.
- `gpu-prices gold-provider-comparison` queries provider floors from `gold.fact_gpu_listings`.
- `gpu-prices export-gold-dashboard` writes public-safe JSON snapshots for static D3 sections.
- `gpu-prices market-hourly` runs the complete provider-to-dashboard heartbeat and writes
  `gold/_manifests/market_runs/latest.json`.

The Windmill schedule is active. The next operational step is to watch the first few cycles for
provider/API, Kafka, S3, and data-quality behavior.

## Second Provider

Lium is the second provider. It uses the same bronze and silver contracts as Vast: raw executor
responses are retained, available executors are normalized into `silver/gpu_offers`, and combined
gold tables are built with:

```sh
uv run gpu-prices build-gold --providers vast,lium
```

The Lium adapter uses `GET /api/executors` with `X-API-Key` authentication, based on the public
OpenAPI document at `https://lium.io/api/openapi.json`.

The current Lium Windmill path writes S3 bronze/silver, publishes Kafka events, and participates in
combined gold. Pagination is enabled by default in the Windmill script and bootstrap helper. The
recurring Kafka-producing Lium job runs from the VPC Windmill worker, the same as Vast, because the
AutoMQ endpoint is private DNS.

The first provider-comparison query shape is:

```sql
select
  gpu_model,
  provider,
  min(price_usd_gpu_hr) as floor_usd_gpu_hr,
  avg(price_usd_gpu_hr) as simple_mean_usd_gpu_hr,
  count(*) as listing_count
from gold.fact_gpu_listings
where availability_status = 'available'
group by gpu_model, provider
order by gpu_model, floor_usd_gpu_hr;
```

## Blog And D3

The personal-site essay can stay as static HTML with D3 sections embedded as progressive
enhancement. The browser should not connect directly to AutoMQ or hold Kafka credentials.

The clean public path is:

```text
gold tables -> DataFusion query/export -> public JSON snapshot -> D3 in the blog post
```

The first snapshot files are:

- `manifest.json`
- `market-run.json`
- `market-history.json`
- `latest-index.json`
- `index-quality.json`
- `index-constituents.json`
- `provider-comparison.json`
- `listings-sample.json`

For local development, write snapshots to `data/dashboard/compute-bazaar/` and serve the repository
root with a local HTTP server. For a public static essay, write the same snapshots to an S3/CloudFront
prefix and point the page at that URL:

```sh
uv run gpu-prices export-gold-dashboard --output-root s3://YOUR_BUCKET/public/compute-bazaar
```

The browser should fetch the public HTTPS form of that prefix, not the private `s3://` URI. The
bucket or CloudFront distribution must allow public reads for those JSON objects and set CORS so
the personal site can fetch them.

Later, live widgets can use:

```text
AutoMQ -> small backend consumer -> safe SSE/WebSocket endpoint -> D3 live view
```

That lets the essay start with stable snapshots, then gain live market elements without exposing
private broker endpoints or secrets.
