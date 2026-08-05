# Compute Bazaar Architecture

The platform is a GPU market-data system: provider APIs are sampled, raw evidence is retained,
offers are normalized, and Gold market products are exposed through DataFusion-backed
queries, dashboard snapshots, and later API/MCP tools.

```mermaid
flowchart LR
  Vast["Provider API: Vast.ai"] --> Windmill["Windmill scheduled workers"]
  Lium["Provider API: Lium"] --> Windmill
  Rates["Official published rate cards"] --> Windmill
  WorkloadPrices["Reviewed processor and memory prices"] --> SandboxBronze["Measured-workload bronze evidence"]
  StarSling["StarSling public benchmark runs"] --> SandboxBronze

  Windmill --> AutoMQ["AutoMQ / Kafka topics"]
  Windmill --> Bronze["S3 bronze: raw JSON evidence"]
  Windmill --> Silver["S3 silver: normalized provider offers"]
  Windmill --> MarketRun["S3 manifest: market run heartbeat"]

  Silver --> DataFusion["DataFusion SQL models"]
  DataFusion --> Gold["S3 gold: maintained market objects"]
  SandboxBronze --> SandboxSilver["Workload silver: runs, jobs, phases, price inputs"]
  SandboxSilver --> DataFusion
  DataFusion --> SandboxGold["Workload gold: estimated job-cost distributions"]
  Bronze --> Workspace["Evidence workspace: raw files, notes, investigations"]
  Workspace --> Gold

  Gold --> CLI["CLI queries"]
  Gold --> API["Future API / MCP"]
  Gold --> Dashboard["D3 blog/dashboard"]
  SandboxGold --> Dashboard
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

DataFusion is the structured transformation and query engine over Parquet lake
tables. Python orchestrates ingestion, execution, storage, manifests, and
publication; relational market calculations live in versioned SQL models under
`src/the_compute_bazaar/sql/models/`. Each executed model is identified by path
and SHA-256 in the Gold manifest.

Gold is the product truth layer. Gold tables are maintained models for comparisons, dashboards,
APIs, CLI queries, agents, and index calculations:

- `gold.fact_gpu_listings`
- `gold.fact_price_index_values`
- `gold.fact_index_constituents`
- `gold.fact_benchmark_values`
- `gold.fact_benchmark_constituents`
- `gold.fact_prime_frontier_offer_history`
- `gold.fact_prime_frontier_offer_events`
- `gold.fact_prime_frontier_offer_reference_history`
- `gold.fact_prime_frontier_offer_ladder`
- `gold.dim_gpu_products`
- `gold.dim_providers`
- `gold.dim_regions`

Consumers should mostly read gold. Silver remains useful for debugging, source-level inspection,
and rebuilding gold when the methodology changes.

The rule is:

```text
Bronze can be messy.
Silver should be standardized.
Gold must be authored.
```

See [sql.md](sql.md) for the SQL model and saved-query boundary.

## Compute Index

The compute index is a first-class gold product, not just an ad hoc query result.

```text
silver/gpu_offers
  -> DataFusion SQL models
  -> gold/fact_gpu_listings
  -> named DataFusion methodology query
  -> gold/fact_price_index_values
  -> gold/fact_price_index_constituents
```

For Stage 1, the index should stay simple and honest:

```text
Compute Bazaar Live Price Index
Indicative advertised GPU-hour benchmark, refreshed hourly
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
evidence, the Gold inputs, and the SQL methodology that produced it.

## Benchmark Products

The H100/H200/B200/B300 benchmark strip is a SQL-authored Gold product. The current
methodology is query-defined in DataFusion SQL:

```text
gold.fact_gpu_listings
  -> benchmark_frontier_gpu_families_v2
  -> gold.fact_benchmark_values
  -> gold.fact_benchmark_constituents
```

The materialized benchmark tables are the hourly published memory of that query. The query and input
manifests are the reproducible methodology. This is why benchmark rows carry both
`methodology_version` and `methodology_query_id`.

Inspection views use the same idea: named SQL files live under
`src/the_compute_bazaar/sql/queries/`, with metadata in
`src/the_compute_bazaar/sql/catalog.json`. The catalog keeps view logic in SQL
rather than Python and preserves the component manifest and lineage chain for
each maintained Gold product. A future query interface should run these files
through the same embedded DataFusion engine.

### Prime Frontier Offer Market

Prime's availability API is also used for one intentionally narrow market
microstructure view:

```text
Prime immutable API snapshots
  -> silver Prime configurations
  -> cumulative H100/H200/B200/B300 offer history
  -> observable lifecycle events
  -> provider-balanced reference history
  -> $0.25 shelf centered on the wider benchmark
  -> public-safe JSON / D3 card / saved SQL
```

Each family reference is the median of one lowest eligible base rate per
upstream provider. The current shelf also carries the matching Compute Bazaar
benchmark so Prime's requestable configurations can be read relative to the
broader market. The shelf groups configurations, not physical GPUs. The event
classifier records appearance, disappearance, stock-label changes, and
repricing, but it never invents fills or cancellations. This keeps the
high-frequency market view useful without promoting catalogue presence into
transaction evidence.

## Sandbox Cost Product

The measured-workload product applies the same layer discipline to the
StarSling HPC Sandbox Benchmark and the reviewed processor-and-memory prices
required to estimate each completed job's cost:

```text
reviewed processor-and-memory price inputs
  + commit-pinned StarSling benchmark evidence
  -> bronze
  -> silver/sandbox_benchmark_batches
  -> silver/sandbox_benchmark_replicates
  -> silver/sandbox_benchmark_phases
  -> silver/sandbox_benchmark_run_metadata
  -> DataFusion methodology queries
  -> gold/sandbox_workload_batch_history
  -> gold/sandbox_workload_latest_replicates
  -> gold/sandbox_workload_latest_phases
  -> gold/sandbox_workload_phase_summary
  -> gold/sandbox_workload_service_summary
  -> gold/sandbox_workload_run_history
  -> dashboard/compute-bazaar/sandbox-cost.json
  -> dashboard/compute-bazaar/sandbox/workload.json
```

The active sandbox product reconstructs complete individual jobs from retained
StarSling phase samples with aligned upstream replicate indices. Its cost field is
`measured_phase_seconds / 3600 * hourly_price`, using only the public
processor-and-memory component. It is a marginal rate-card estimate, not a
provider bill.

The historical workload table retains 80 provider-batch means from fourteen source
runs. Those batches cross thirteen harness revisions, so history is stratified by
methodology rather than rendered as one homogeneous performance series.
Lifecycle latency, queueing, reliability, and concurrency remain separate
future measurements.

DataFusion also groups the retained provider-batch rows by source run into
`sandbox_workload_run_history`. Each row carries service count, fixed-cohort
completeness, median/p25/p75 runtime, median/p25/p75 estimated
processor-and-memory cost, source run ID, source commit, and methodology ID.
All fourteen source runs remain present, including repeated intraday runs. The
article's headline history uses only the ten runs containing all six fixed
services; it does not rewrite incomplete runs or average them by day.

The old sparse sandbox rate-card history and common-start GPU/VM/sandbox chart
are archived and no longer published. Runtime remains in Gold because it is
required to reproduce each cost, while the public product focuses on estimated
cost per completed benchmark job.

The market-state product separately publishes source-reported active or rented
capacity where numerator and denominator exist. Akash CPU, GPU, memory, and
storage units, Clore public servers, and Prime configurations remain distinct
series. The article pairs each selected share with its source numerator,
denominator, unit, and scope; those counts are capacity observations, not
transaction volume, and no statistical band is inferred.

The public measured-workload card advances only after the daily source poll
finds another compatible StarSling generation. It presents estimated cost per
completed job. Runtime remains in Gold solely to reproduce and audit that cost.

The hourly Windmill heartbeat rebuilds the workload-cost Gold projection after
GPU dashboard history is exported. A separate daily source check detects new
or changed StarSling evidence. Processor-and-memory price inputs are reviewed
manually because provider billing semantics are not safely interchangeable or
uniformly machine-readable.

See [sandbox-cost-benchmark.md](sandbox-cost-benchmark.md) for the complete
measurement and maintenance contract.

## Workspace / Evidence Layer

The future agent workspace is not Gold. It is where agents and operators can do messy investigation:

- inspect raw S3 evidence
- grep provider files or docs
- compare unusual listings
- write anomaly notes
- produce candidate labels

Those artifacts can become Gold only after validation promotes them into a controlled
label, signal, score, or narrative table.

## Current Stage

Stage 1 is live:

- Windmill runs direct live APIs, public cross-cloud catalogs, cloud price
  observations, and separately labeled published rate cards from inside the
  AWS VPC.
- The default source set is Vast, Lium, Spheron, Inference.sh, GridStackHub,
  Cloud GPU Prices, Thunder Compute, Vultr, Scaleway, Oracle Cloud, OVHcloud,
  Akash, RunPod, and Verda. AWS Spot and Azure retail are current price
  observations but are not proof of deployable capacity. External aggregators
  are retained for discovery and comparison but cannot vote in the benchmark.
- Optional authenticated connectors cover Clore, Prime Intellect, Shadeform,
  Sesterce, TensorDock, Hyperstack, Lambda Cloud, DigitalOcean, GPUs.io,
  JarvisLabs, and Verda availability.
- The heartbeat can also ingest official published rate cards from Runpod, Lambda, Hyperstack,
  Nebius, Crusoe, Civo, Denvr, DigitalOcean, GMI Cloud, Hyperbolic, Koyeb,
  Massed Compute, TensorDock, Verda, VESSL, and Voltage Park as clearly marked
  provider observations.
- Raw provider responses are written to S3 bronze. Lium stores a raw pagination envelope so the
  bronze layer contains page-level provider evidence, not just extracted rows.
- Normalized offers are written to S3 silver.
- Source-defined capacity observations are written to
  `silver/compute_market_state`. Rental occupancy is admitted only when a
  source supplies both the rented numerator and matching total denominator.
- AutoMQ receives provider snapshot and normalized offer events.
- AutoMQ also receives `gpu.market_state_observation.v1` events.
- DataFusion queries the latest Silver and Gold Parquet tables.

Stage 1.5 is operating:

- The hourly Python market service builds Gold tables from retained Silver.
- DataFusion queries index values, constituents, provider comparisons,
  benchmark values, market state, and measured-workload costs.
- Saved SQL provides reviewed reusable questions over the latest Gold manifest.
- The public exporter writes sanitized JSON snapshots for static D3 sections.
- Windmill calls the market service directly and writes
  `gold/_manifests/market_runs/latest.json` for the complete heartbeat.

The Windmill schedule is active. GPU and measured-workload Gold manifests point
to immutable run/build generations. Operational status describes whether
ingestion and publication worked; unknown GPU aliases are retained separately
as normalization/data-quality debt. An hourly external check watches the public
workload-cost projection, while the underlying StarSling observation advances
only when the upstream project publishes another compatible run.

The market-run manifest records operational health separately from product
availability. A partial upstream failure therefore remains visible even when
the pipeline writes a coherent Gold generation from the other sources. The
public article stays a smaller narrative projection; it is not the place to
expose every table or private lake reference.

The capacity-state path has two gold tables:

- `fact_compute_market_state` is the latest cross-section.
- `fact_compute_market_state_history` cumulatively retains hourly observations
  by stable observation ID.

Akash's network rows divide active capacity by total capacity from the same
online providers for CPU (millicores), GPU units, memory bytes, and storage
bytes. Official Akash operations documentation describes active inventory as
resources consumed by deployments. Clore's row is server weighted and
on-demand only: public servers with `rented=true` divided by public servers
with that flag. Prime divides configurations carrying an available stock
status by all configurations returned for the same upstream provider and GPU
product. These rows can share a percentage scale but are not pooled because
their units and market scopes differ. Prime Intellect keeps the upstream seller
in `provider`; when the same provider/model is available from a direct
connector, the aggregate observation stays auditable but is marked ineligible
for aggregation.

Clore requires `CLORE_API_KEY`. If that key is absent, it is omitted from the
hourly provider scope; previous source observations remain in historical gold.

The full model-level state stays in these gold tables and remains queryable
through DataFusion. The public `market-state.json` export contains the current
occupancy and availability cross-section, but limits public history to
aggregate CPU, GPU, memory, and storage rows. That keeps the static article
payload bounded without making the publication file the system of record.

## Direct Provider Example

Lium uses the same bronze and silver contracts as Vast: raw executor
responses are retained, available executors are normalized into
`silver/gpu_offers`, and the hourly market service includes both providers in
the DataFusion Gold build.

The Lium adapter uses `GET /api/executors` with `X-API-Key` authentication, based on the public
OpenAPI document at `https://lium.io/api/openapi.json`.

The current Lium Windmill path writes S3 bronze/silver, publishes Kafka events, and participates in
combined gold. Pagination is enabled by default in the Windmill script and bootstrap helper. The
recurring Kafka-producing Lium job runs from the VPC Windmill worker, the same as Vast, because the
AutoMQ endpoint is private DNS.

Aggregate catalogs keep the actual upstream seller in `provider` and the feed
used to observe it in `source_connector`. Benchmark provider floors therefore
remain seller-level. Capacity coverage first sums each seller/connector lower
bound, then keeps the maximum connector total for that seller; direct and
aggregate observations of the same inventory are not added together.

## Published Rate Cards

Live marketplace providers are not enough for a credible frontier benchmark when one provider has
thin H100/H200/B200/B300 coverage. The platform now supports provider-published rate-card
observations as a separate ingestion path. These rows are sourced from official public provider
pricing pages, written to bronze as `rate-card.json`, normalized to `silver/gpu_offers`, and then
included in combined gold builds.

Current published-rate providers:

- Runpod
- Lambda
- Hyperstack
- Nebius
- Crusoe
- Denvr
- TensorDock
- GMI Cloud
- Massed Compute
- Verda
- VESSL
- Voltage Park
- DigitalOcean
- Civo
- Koyeb
- Hyperbolic

These rows are not live inventory. Each keeps a source URL, source-check time,
price basis, and access mode. Current hourly and request-based advertised rates
can enter the benchmark; future and reserved rates remain queryable evidence
but are excluded. Procurement and execution still need live provider APIs.

The frontier benchmark first selects one eligible floor per provider and GPU
family, then publishes the median of those provider floors. This prevents a
marketplace with many rows from receiving accidental extra weight. See
`docs/benchmark-methodology.md` for the complete contract.

The first provider-comparison query shape is:

```sql
select
  gpu_model,
  provider,
  min(price_usd_gpu_hr) as floor_usd_gpu_hr,
  avg(price_usd_gpu_hr) as simple_mean_usd_gpu_hr,
  count(*) as listing_count
from gold.fact_gpu_listings
where availability_status in ('available', 'published_rate')
group by gpu_model, provider
order by gpu_model, floor_usd_gpu_hr;
```

## Blog And D3

The personal-site essay can stay as static HTML with D3 sections embedded as progressive
enhancement. The browser should not connect directly to AutoMQ or hold Kafka credentials.

The clean public path is:

```text
Gold tables -> public JSON snapshot -> D3 in the blog post
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
prefix and point the page at that URL. The hourly market service performs this
export after a successful Gold build.

The browser should fetch the public HTTPS form of that prefix, not the private `s3://` URI. The
bucket or CloudFront distribution must allow public reads for those JSON objects and set CORS so
the personal site can fetch them.

Later, live widgets can use:

```text
AutoMQ -> small backend consumer -> safe SSE/WebSocket endpoint -> D3 live view
```

That lets the essay start with stable snapshots, then gain live market elements without exposing
private broker endpoints or secrets.
