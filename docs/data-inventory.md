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
| Prime frontier offer market | Hourly Windmill market run when `PRIME_INTELLECT_API_KEY` is configured | Paginated H100, H200, B200, and B300 availability responses retained with each provider run | Prime configurations with upstream provider, `cloudId`, datacenter, shape, socket, stock label, base rate, and minimum separately billed resources | Cumulative four-family offer history, observable lifecycle events, provider-balanced references, and benchmark-centered $0.25 shelves | Multi-product offer card, saved SQL, and future sourcing context |
| Compute market state | Hourly where the source exposes a usable measure | Provider response retained with the provider run | `lake/silver/compute_market_state/...` | `fact_compute_market_state` and cumulative deduplicated `fact_compute_market_state_history` | Akash active/total CPU, GPU, memory, and storage capacity; Clore rental occupancy; Prime and direct-provider availability |
| StarSling measured workload cost | Daily public source poll; upstream publication cadence | Immutable benchmark evidence, retrieval references, checksums, and reviewed processor-and-memory price inputs | Content-addressed run metadata, complete jobs, phases, machine shape, and source linkage | Latest job-cost distribution, service and phase summaries, compatible run history, and one source-run summary per retained run | Estimated processor-and-memory cost per completed StarSling benchmark job |
| Archived VM and sandbox rate-card research | No active refresh | Historical exact-shape VM observations and 33 manually reviewed sandbox quotes remain retained for later research | Historical generated tables may exist in old immutable generations | Not referenced by the current Gold manifest | No active chart, endpoint, or publication |

## History Contracts

### GPU offers and benchmarks

- Every provider run has its own run ID and raw reference.
- Silver offers are append-only partitions rather than a mutable current table.
- Gold rebuilds from retained manifests and writes methodology-versioned values
  plus constituents.
- A benchmark value is not complete without its provider count, included
  offers, excluded rows, methodology version, and source run references.
- Prime's `gpuCount` is a machine-shape field, not an available-inventory
  count. The Prime frontier shelves count returned configurations and distinct
  upstream providers only.
- A missing Prime configuration is retained as `left_availability`; it is not
  relabeled as a rental, fill, cancellation, or occupancy observation.
- The four Prime reference histories are cumulative and deduplicated by Gold
  run and stable listing identity. A current export can therefore be rebuilt
  without making the browser the historical store.

### Archived VM and sandbox prices

- The old exact-shape VM observations and managed-sandbox rate-card quotes are
  retained as research evidence, not as a live market feed.
- The 33 sandbox observations are sparse public quotes whose billing unit is
  hourly; that does not make their observation cadence hourly.
- Current Gold manifests and public projections do not reference these tables.

### Workload benchmark

- Earlier two-processor runs are retained in bronze but rejected from the
  four-processor comparison.
- The latest batch contains 72 complete replicate-aligned jobs and 720 task
  phase rows. Missing replicate slots are never imputed.
- Historical evidence contains 80 provider-batch summaries from fourteen source
  runs over eleven days and thirteen harness methodologies.
- `sandbox_workload_run_history` preserves those fourteen source runs separately,
  including repeated intraday runs. Ten runs contain the complete fixed
  six-service cohort and are eligible for the article headline history; four
  incomplete runs remain in gold and the public audit payload.
- Those 80 rows are durable audit history, not one homogeneous performance
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
dashboard/compute-bazaar/prime-frontier-offer-market.json
dashboard/compute-bazaar/prime-frontier-offer-shelf.json
dashboard/compute-bazaar/prime-h100-offer-reference.json
dashboard/compute-bazaar/sandbox-cost.json
dashboard/compute-bazaar/sandbox/workload.json
dashboard/compute-bazaar/market-state.json
dashboard/compute-bazaar/manifest.json
```

The archived sandbox prices are not part of this public contract. New
frontends should compose active Gold objects for the question they need rather
than copying calculations into JavaScript.

The article filters precomputed Gold series into display windows and draws
them. It does not calculate the H100 benchmark or StarSling cost distribution
in the browser. The measured-workload card presents estimated cost; runtime
remains an auditable Gold field required by the cost formula.

The packaged SQL catalog contains the maintained read-only inspection queries.
It operates over tables declared by the latest Gold manifests while preserving
explicit units and component lineage. The public article reads only sanitized
publication JSON.

## Refresh And Verification

The hourly market heartbeat is the Windmill script:

```sh
uv run python infra/windmill/bootstrap_market_schedule.py --run-now --wait
```

The measured-workload layer can be rebuilt independently:

```sh
uv run sandbox-cost validate

uv run sandbox-cost build \
  --output-root data/lake/sandbox_cost \
  --dashboard-output-root data/dashboard/compute-bazaar

uv run sandbox-cost refresh-benchmark \
  --output-root data/lake/sandbox_cost \
  --source-repository OWNER/hpc-sandbox-benchmarks \
  --source-ref main \
  --publish-operational
```

Check the deployed projection separately:

```sh
uv run sandbox-cost check-public \
  --url https://bazaar.adamsioud.com/sandbox-cost.json \
  --max-age-hours 2.5
```

The daily `.github/workflows/measured-workload-sources.yml` job validates canonical
evidence, detects new or changed public StarSling runs, and runs focused tests. A separate daily
Windmill source poll promotes compatible public commits into operational
bronze and silver. It has no benchmark credentials and launches no workloads.
Windmill remains responsible for the market heartbeat and S3 history. The hourly
`.github/workflows/public-feed-freshness.yml` job checks the deployed public
projection.

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

## Local Cloud Archive

The complete current S3 data estate can be retained under the ignored local
`data/cloud-archive/` tree. The archive stores each payload once by SHA-256,
materializes the original bucket/key hierarchy with hard links, and writes a
snapshot manifest containing the source ETag, size, last-modified time, and
local checksum for every object.

The archive implementation remains in
`the_compute_bazaar.prices.archive`. Its next public interface belongs in the
small DataFusion-oriented CLI rather than the removed ingestion command router.

The default source is the full bucket inferred from the configured raw, lake,
and dashboard roots. Re-running the command reuses unchanged content-addressed
blobs and downloads only new or changed current objects. Snapshot manifests
remain under `snapshots/`; old blobs are retained when a mutable S3 key changes.

To operate without AWS access:

```sh
source data/cloud-archive/offline.env
uv run compute-bazaar-adamsioud
```

`COMPUTE_BAZAAR_S3_MIRROR_ROOT` resolves the unchanged `s3://` references in
historical manifests to local files. DataFusion therefore runs the same named
queries over the archived Parquet objects; manifests and evidence are not
rewritten to pretend that local paths were their original source.

The archive contains current S3 objects, including the immutable bronze,
silver, gold, market-run, dashboard, and publication histories already
retained as separate keys. Bucket versioning is enabled, but the current IAM
user does not have `s3:ListBucketVersions`; overwritten historical object
versions and delete markers are therefore outside this archive until that
read-only permission is granted.

S3 keys whose individual path components exceed the local filesystem limit
are stored under deterministic `.s3-long-keys/` paths. Their original keys
remain in the archive manifest, and the mirror resolver handles them normally;
do not treat the materialized directory layout alone as the object index.

This folder protects against losing cloud access, but a copy on the same
laptop is not an independent hardware backup. Periodically refresh the archive,
then copy the complete `data/cloud-archive/` directory to an external disk or
another account-controlled storage location. If it is moved,
update `COMPUTE_BAZAAR_S3_MIRROR_ROOT` in `offline.env` to the new absolute
`objects/` path.

AutoMQ remains a transient event tape rather than the durable market record.
Provider snapshots, normalized offers, and market-state observations are
reconstructible from S3 bronze and silver. A Kafka topic export can be kept as
an additional operational artifact, but loss of AutoMQ does not remove the
evidence or query history represented by this archive.
