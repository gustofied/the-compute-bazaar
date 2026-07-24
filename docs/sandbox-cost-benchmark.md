# Sandbox Cost Benchmark

The sandbox-cost benchmark is a maintained Compute Bazaar product used by the
AdamSioud Compute article. It separates three questions:

1. What is the public processor-and-memory hourly price for the same nominal
   machine shape?
2. How long did the same public software job take, and what is its estimated
   processor-and-memory cost?
3. How did the sandbox-price average and the existing H100 observed benchmark
   move relative to their first shared observation?

It does not present the normalized hourly price as a complete invoice, and it
does not put raw GPU dollars and sandbox-job cents on one axis.

## Maintained Data Path

```text
official price pages + archived observations
  -> versioned hourly-price evidence
StarSling public benchmark repository
  -> commit-pinned raw captures
  -> shape and schema validation
  -> versioned benchmark evidence
both evidence sets
  -> bronze source records
  -> silver normalized Parquet
  -> DataFusion methodology queries
  -> gold publication tables
  -> sandbox-cost.json
  -> AdamSioud D3 article
```

The canonical reviewed evidence is packaged under:

```text
src/the_compute_bazaar/sandbox_cost/evidence/
```

Runtime lake output is written below the selected `--output-root`:

```text
bronze/hourly-price-evidence.json
bronze/benchmark-evidence.json
bronze/source-manifest.json
bronze/hpc-sandbox-benchmarks/commit=<sha>/...
silver/sandbox_hourly_prices.parquet
silver/sandbox_benchmark_runs.parquet
silver/gpu_benchmark_history.parquet
gold/sandbox_hourly_price_series.parquet
gold/sandbox_fixed_average.parquet
gold/sandbox_same_job_cost.parquet
gold/sandbox_combined_base100.parquet
gold/manifest.json
```

Bronze preserves evidence and retrieval metadata. Silver standardizes units,
dates, timing precision, machine shape, runtime, and provenance. Gold contains
publication-ready products computed by named DataFusion queries.

## Current Evidence

The reviewed hourly-price record contains 33 observations for 11 services from
November 2024 through July 2026. The normalized shape is:

```text
4 virtual processors
8 GiB memory
```

The benchmark comparison also requires a 40 GB disk because that is part of the
public StarSling run specification. The current StarSling source contains 38
service results from seven shape-compatible runs over five calendar days,
19-23 July 2026. Repeated intraday runs are retained. Earlier source runs with
two processors are captured in bronze and rejected before silver.

Provider billing bases are not identical. For example, some pages quote
allocated virtual processors and memory, some meter actual use, and some derive
processor capacity from memory. The article therefore says “public hourly
price for four processors and 8 GB of memory” and “processor-and-memory
estimate,” not “identical bill.”

The canonical source manifest pins the audited StarSling source commit and
records SHA-256 checksums for the index, methodology, and run files. Each price
observation retains its public source URL and one of these date meanings:

- `effective`: the provider states when the rate took effect.
- `observed`: the date on which the public quote was captured.
- `between_observations`: the quote changed between two checks, so only the
  first later observation is known.
- `same_quote`: a later check confirmed the same quote.

## Formulas

Normalized hourly price:

```text
processor quantity * processor rate per unit-hour
  + memory GiB * memory rate per GiB-hour
```

Same-job runtime:

```text
sum of the ten published Better Auth mean task times
```

Estimated same-job cost:

```text
runtime_seconds / 3600 * matching hourly processor-and-memory price
```

The estimate excludes storage, network, subscriptions, credits, retries, idle
time, and work outside the ten measured tasks.

The fixed average is calculated over the same eight services at every event
date:

```text
E2B, Daytona, Vercel, Novita, Modal, Runloop, Blaxel, Fly.io
```

This prevents a service entering the record from moving the average merely by
changing membership.

The exploratory combined view uses compatible H100 gold history only:

```text
benchmark_family_id = H100
methodology_version = advertised_provider_floor_median_v1
benchmark_basis = advertised_hourly
```

At each H100 observation it carries forward the latest dated sandbox average,
then rebases each series:

```text
base_100 = value / first_shared_value * 100
```

DataFusion-computed floating values are canonicalized to 12 decimal places at
the Gold boundary. The precision rule is part of the build identity. This
removes harmless processor-level floating differences so a Linux Windmill build
and a local build from identical inputs produce byte-identical publication
JSON.

It can show relative movement from a shared starting point. It cannot establish
price-level equivalence, demand, transaction volume, or complete customer cost.
The H100 provider set expands over the retained period, so movement can reflect
both observed quotes and changing provider coverage. The chart is exploratory,
not a fixed-membership GPU index.

## Commands

Validate reviewed evidence:

```sh
uv run sandbox-cost validate
```

Build all lake layers and the article payload:

```sh
uv run sandbox-cost build \
  --output-root data/sandbox-cost \
  --dashboard-output-root data/dashboard/compute-bazaar \
  --gpu-history-ref data/dashboard/compute-bazaar/benchmark-history.json
```

Run an allowlisted gold query through DataFusion:

```sh
uv run sandbox-cost query \
  --output-root data/sandbox-cost \
  --query same-job-cost \
  --limit 10
```

Available query IDs are `hourly-prices`, `fixed-average`, `same-job-cost`, and
`combined-base100`.

Fetch and validate the public benchmark repository without changing reviewed
evidence:

```sh
uv run sandbox-cost refresh-benchmark \
  --output-root data/sandbox-cost \
  --source-ref main \
  --check
```

`--check` exits nonzero when compatible evidence is new. Review the captured
bronze files and source changes before running:

```sh
uv run sandbox-cost refresh-benchmark \
  --output-root data/sandbox-cost \
  --source-ref <reviewed-commit> \
  --update-evidence
```

Never combine `--check` and `--update-evidence`. Existing result values cannot
change silently; the historical merge fails if a source rewrites a known run.

## Recurrence

The existing Windmill `market_hourly` job builds gold GPU data and public
dashboard snapshots once per hour. It now also builds sandbox bronze, silver,
gold, and `sandbox-cost.json` from the reviewed evidence and the newly exported
GPU benchmark history. This keeps the article payload synchronized with the
hourly GPU feed.

`.github/workflows/sandbox-cost-sources.yml` runs daily and on demand. It
validates canonical evidence, fetches the public StarSling source, detects
schema drift or new matching runs, and runs focused tests. A failed source check
is a review request, not permission to publish changed measurements.

The scheduled check deliberately does not clone the private AdamSioud
submodule. It verifies the public data package and source contract without
requiring a cross-repository secret. Run `tests.test_adamsioud` when preparing
the private article publication.

The public price pages do not provide one stable, semantically equivalent API.
Price review therefore remains manual:

1. Open every source URL retained in the latest price ledger.
2. Verify the billing basis, machine normalization, currency, and effective or
   observed date.
3. Add a new immutable observation; do not replace history.
4. Run `sandbox-cost validate`, the focused tests, and a deterministic build.
5. Inspect the article ledger and hover details before publishing.

This boundary is deliberate. Scraping marketing pages automatically would make
the feed look fresher while weakening the evidence.

## Publication

The public-safe file is:

```text
dashboard/compute-bazaar/sandbox-cost.json
```

The AdamSioud article first reads the configured CloudFront dashboard base, then
falls back to the checked-in `exemplars/compute/sandbox-cost.json` for local or
static operation. Raw captures and lake refs remain private.

Article source:

```text
external/AdamSioud/exemplars/compute/feeling_the_compute.html
external/AdamSioud/exemplars/compute/sandbox-cost.js
```

Public page:

```text
https://www.adamsioud.com/exemplars/compute/feeling_the_compute.html
```

## Focused Verification

```sh
uv run python -m unittest \
  tests.test_sandbox_cost \
  tests.test_adamsioud

node --check external/AdamSioud/exemplars/compute/sandbox-cost.js
```

The tests cover formulas, exact shape matching, duplicate rejection, source
retention, schema drift, repeated intraday runs, immutable historical merges,
DataFusion execution, deterministic output, generated frontend data, and the
article integration contract.
