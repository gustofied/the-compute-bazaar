# Compute Bazaar Data Inventory

This document records which datasets exist, where their durable history lives,
how they refresh, and which layer a frontend should read. It is the operating
map for rebuilding an article, dashboard, CLI view, API, or agent tool without
depending on an existing presentation.

## Authority Order

Use this order when two copies disagree:

1. The S3 bronze and lake prefixes configured by
   `COMPUTE_BAZAAR_RAW_ROOT` and `COMPUTE_BAZAAR_LAKE_ROOT` are the
   operational history.
2. Versioned evidence under `src/the_compute_bazaar/sandbox_cost/evidence/`
   and commit-pinned benchmark captures are the reproducible source record for
   manually reviewed datasets.
3. Gold Parquet and its manifest are the product truth consumed by queries.
4. `dashboard/compute-bazaar/*.json` is a public-safe projection. It is
   replaceable and must not be the only retained history.
5. The ignored local `data/` tree is a development cache. It can lag S3 and is
   never proof of current production state.

## Dataset Register

| Dataset | Cadence | Bronze | Silver | Gold | Publication use |
| --- | --- | --- | --- | --- | --- |
| GPU provider offers | Hourly Windmill market run | One immutable provider response and manifest per run under `raw/provider=.../date=.../run_id=...` | Per-run normalized offers under `lake/silver/gpu_offers/...` | Listings, provider/GPU/region dimensions, index values and constituents, benchmark values and constituents | GPU cards, price history, provider comparison, future search/API |
| Prime H100 offer shelf | Hourly Windmill market run when `PRIME_INTELLECT_API_KEY` is configured | Prime paginated availability response retained with each provider run | Prime configurations with upstream provider, `cloudId`, datacenter, shape, socket, stock label, base rate, and minimum separately billed resources | Cumulative offer history, observable lifecycle events, provider-balanced reference history, and centered $0.25 ladder | H100 reference/ladder card, Curia queries, future sourcing context |
| Compute market state | Hourly where the source exposes a usable measure | Provider response retained with the provider run | `lake/silver/compute_market_state/...` | `fact_compute_market_state` and cumulative deduplicated `fact_compute_market_state_history` | Akash active/total CPU, GPU, memory, and storage capacity; Clore rental occupancy; Prime and direct-provider availability |
| Exact-shape VM offers | Hourly Windmill market run | Official catalog responses under `raw/sandbox-cost/vm-capacity/...` and discovery prefixes, with retrieval time and checksum | Cumulative offer, discovery, marketplace, current, and expanded-cohort Parquet tables under `lake/sandbox_cost/silver/` | Current seven-vendor cross-section; hourly median/p25/p75/min/max in USD and base-100 form; legacy four-vendor history; separate marketplace indication | VM-versus-sandbox reference, relative-price comparison, and source audit |
| Managed sandbox rate cards | Manual reviewed evidence; gold rebuilt hourly | Versioned source register, archived URLs, dates, and arithmetic in package evidence and `lake/sandbox_cost/bronze/` | `sandbox_hourly_prices.parquet` | Current rates, fixed eight-service median/p25/p75, and dated price events | Public sandbox rate comparison |
| StarSling workload runs | Daily public source poll; upstream publication cadence | One immutable retrieval capture and checksum ledger per poll | Content-addressed run metadata, provider-batch summaries, replicate-aligned jobs, and task phases | Latest job distribution, service summaries, phase summaries, all compatible historical provider-batch summaries, and one source-run summary per retained run | Same-workload estimated processor-and-memory cost and measured-runtime history |
| GPU/VM/sandbox relative prices | Rebuilt after each market run | Uses retained GPU, VM, and sandbox evidence above | Uses eligible GPU benchmark history, exact VM offer history, and normalized sandbox prices | H100/sandbox common-start series, independently based VM series, and H100 coverage history | Exploratory relative advertised-rate chart only |

## History Contracts

### GPU offers and benchmarks

- Every provider run has its own run ID and raw reference.
- Silver offers are append-only partitions rather than a mutable current table.
- Gold rebuilds from retained manifests and writes methodology-versioned values
  plus constituents.
- A benchmark value is not complete without its provider count, included
  offers, excluded rows, methodology version, and source run references.
- Prime's `gpuCount` is a machine-shape field, not an available-inventory
  count. The Prime H100 ladder counts returned configurations and distinct
  upstream providers only.
- A missing Prime configuration is retained as `left_availability`; it is not
  relabeled as a rental, fill, cancellation, or occupancy observation.
- The Prime reference history is cumulative and deduplicated by Gold run and
  stable listing identity. A current export can therefore be rebuilt without
  making the browser the historical store.

### VM capacity

- Each successful hourly check is an observation even when the catalog price
  did not change.
- Repeating the same source and observation timestamp is idempotent.
- A conflicting value at an already retained identity fails rather than
  replacing history.
- The seven-vendor series begins with the first complete seven-source check.
  The earlier four-vendor cohort remains a separate methodology and is never
  relabeled as seven-vendor history.
- Akash is a modeled request indication and stays outside the vendor median.

### Sandbox prices

- Historical rows are actual stated effective, published, observed, or bounded
  dates. The build does not invent hourly history between source checks.
- The fixed eight-service cohort preserves membership so discovering another
  service cannot rewrite the historical median.
- Marketing-page semantics require review. The hourly job rebuilds the latest
  gold/public projection from canonical evidence; it does not claim that all
  sandbox price pages were fetched again that hour.

### Workload benchmark

- Earlier two-processor runs are retained in bronze but rejected from the
  four-processor comparison.
- The latest batch contains 69 complete replicate-aligned jobs and 690 task
  phase rows. Missing replicate slots are not imputed.
- Historical evidence contains 38 provider-batch summaries from seven source
  batches over five days and six harness methodologies.
- `sandbox_workload_run_history` preserves those seven source runs separately,
  including both 22 July intraday runs. Three runs contain the complete fixed
  six-service cohort and are eligible for the article headline history; four
  incomplete runs remain in gold and the public audit payload.
- Those 38 rows are durable audit history, not one homogeneous performance
  time series. A frontend may inspect or group them by methodology, but must
  not draw one smooth line across harness revisions.
- Workload execution belongs to the upstream StarSling project. Compute Bazaar
  only polls public committed results and does not pay for or dispatch runs.
- `--publish-operational` is an explicit trust boundary. It accepts only the
  pinned target shape and workload signature, rejects source rewrites, retains
  every source poll, writes a content-addressed silver generation, and refuses
  to drop any reviewed historical run.
- The next hourly market build reads
  `silver/_manifests/workload_benchmark/latest.json` automatically. DataFusion
  then produces the workload gold tables and public projection. A source poll
  does not invent a new benchmark observation when the source dataset did not
  change.

## Frontend Contract

A frontend should request publication JSON or an API backed by gold, but every
displayed number must remain reproducible from gold and traceable through
silver to bronze.

The maintained public files are:

```text
dashboard/compute-bazaar/featured-benchmarks.json
dashboard/compute-bazaar/benchmark-history.json
dashboard/compute-bazaar/prime-h100-offer-reference.json
dashboard/compute-bazaar/sandbox-cost.json
dashboard/compute-bazaar/market-state.json
dashboard/compute-bazaar/manifest.json
```

The article intentionally shows fewer views than the payload contains. Hidden
or removed charts do not delete their underlying data. New frontends should
compose the existing gold objects for the question they need rather than
copying calculations into JavaScript.

The article's market pulse is one such composition. It filters precomputed gold
series into 1D, 7D, 1M, and All windows and draws them. It does not calculate
the H100 benchmark, VM median, capacity shares, StarSling medians, or
percentiles in the browser.

The internal `/operator/` surface is the full read-only view. It composes the
latest GPU and sandbox/VM gold manifests, registers their Parquet tables in
DataFusion, and exposes named catalog queries plus bounded scratch SQL. The
catalog is the correct place to compare prices while retaining explicit units,
inspect measured workload costs, and trace rows back through component
manifests. The public article continues to read only sanitized publication
JSON.

## Refresh And Verification

The hourly market heartbeat is:

```sh
uv run gpu-prices market-hourly
```

The sandbox/VM layer can be rebuilt independently:

```sh
uv run sandbox-cost validate

uv run sandbox-cost refresh-vm-capacity \
  --output-root data/lake/sandbox_cost \
  --raw-root data/raw

uv run sandbox-cost refresh-vm-discovery \
  --output-root data/lake/sandbox_cost \
  --raw-root data/raw

uv run sandbox-cost build \
  --output-root data/lake/sandbox_cost \
  --dashboard-output-root data/dashboard/compute-bazaar \
  --gpu-history-ref data/lake/sandbox_cost/silver/gpu_benchmark_history.parquet \
  --vm-capacity-history-ref data/lake/sandbox_cost/silver/vm_capacity_offer_history.parquet \
  --vm-capacity-current-ref data/lake/sandbox_cost/silver/vm_capacity_current.parquet \
  --vm-capacity-manifest-ref data/lake/sandbox_cost/silver/vm_capacity_source_manifest.json \
  --vm-discovery-history-ref data/lake/sandbox_cost/silver/vm_capacity_discovery_history.parquet \
  --vm-discovery-current-ref data/lake/sandbox_cost/silver/vm_capacity_discovery_current.parquet \
  --vm-discovery-manifest-ref data/lake/sandbox_cost/silver/vm_capacity_discovery_manifest.json

uv run sandbox-cost refresh-benchmark \
  --output-root data/lake/sandbox_cost \
  --source-repository OWNER/hpc-sandbox-benchmarks \
  --source-ref main \
  --publish-operational
```

Check the deployed projection separately:

```sh
uv run sandbox-cost check-public \
  --url https://d3n0n6h709c83f.cloudfront.net/sandbox-cost.json \
  --max-age-hours 2.5
```

The daily `.github/workflows/sandbox-cost-sources.yml` job validates canonical
evidence, detects new or changed public StarSling runs, checks the first
exact-shape VM source schemas, and runs focused tests. A separate daily
Windmill source poll promotes compatible public commits into operational
bronze and silver. It has no benchmark credentials and launches no workloads.
Windmill remains responsible for the full hourly source set and S3 history. The hourly
`.github/workflows/public-feed-freshness.yml` job checks that the public
projection and latest complete VM observation have not gone stale.

## Recovery Checklist

When a chart or API needs to be rebuilt:

1. Read the latest market-run and gold manifests.
2. Confirm the required gold table and methodology ID exist.
3. Query gold with DataFusion; do not calculate the product metric in the
   browser.
4. Follow constituent or source references into silver when row-level detail is
   needed.
5. Follow raw references into bronze for evidence or parser debugging.
6. Export a new public-safe JSON projection.
7. Verify freshness, row counts, units, source links, and responsive rendering.
