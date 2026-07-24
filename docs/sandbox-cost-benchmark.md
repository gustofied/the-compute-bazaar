# Sandbox Cost Benchmark

The sandbox-cost benchmark is a maintained Compute Bazaar data product used by
the AdamSioud Compute article. It answers three separate questions:

1. What advertised processor-and-memory rate do public sandbox services quote
   for one normalized machine?
2. How long did one public software workload take on comparable machines, and
   what processor-and-memory cost does that runtime imply?
3. How did a coverage-eligible H100 observed quote benchmark and the sandbox
   cohort rate move after one declared common starting point?

The distinctions are deliberate. An advertised rate is not an invoice, a
runtime is not a rate, an estimated cost is not a charge, provider count is not
volume, and an observed offer is not an executed transaction.

## Maintained Data Path

```text
official price pages + archived observations
  -> versioned sandbox price evidence
StarSling public benchmark repository
  -> commit-pinned raw captures
  -> shape and schema validation
Compute Bazaar GPU benchmark history
  -> retained observed-offer prints and provider coverage
all compatible inputs
  -> bronze source records
  -> silver normalized Parquet
  -> named DataFusion queries
  -> gold publication tables
  -> sandbox-cost.json
  -> AdamSioud D3 article
```

Canonical reviewed sandbox evidence is packaged under:

```text
src/the_compute_bazaar/sandbox_cost/evidence/
```

Runtime output below the selected `--output-root` is:

```text
bronze/hourly-price-evidence.json
bronze/benchmark-evidence.json
bronze/source-manifest.json
bronze/hpc-sandbox-benchmarks/commit=<sha>/...

silver/sandbox_hourly_prices.parquet
silver/sandbox_benchmark_runs.parquet
silver/gpu_benchmark_history.parquet

gold/sandbox_hourly_price_series.parquet
gold/sandbox_price_events.parquet
gold/sandbox_current_rates.parquet
gold/sandbox_fixed_rate.parquet
gold/sandbox_same_job_cost.parquet
gold/sandbox_same_job_summary.parquet
gold/gpu_h100_daily_coverage.parquet
gold/gpu_h100_eligible_history.parquet
gold/sandbox_gpu_cpu_common_start.parquet
gold/manifest.json
```

Bronze preserves evidence and retrieval metadata. Silver standardizes units,
dates, timing precision, machine shape, runtime, and provenance. Gold contains
publication-ready products computed by named, hashed DataFusion queries.

## Evidence and Scope

The reviewed price record contains 33 observations for 11 services from
November 2024 through 24 July 2026. Every observation retains its original URL,
date meaning, source class, normalization inputs, and explanatory note.

The normalized sandbox shape is:

```text
4 vCPU equivalent
8 GiB memory
```

Where a public service bills physical cores, the evidence uses two vCPUs per
physical core. This is a shape conversion, not a claim that every processor,
host, scheduler, or tenancy model performs identically. The workload comparison
also requires a 40 GB disk because that is part of the public StarSling target
specification.

The current StarSling source contains 38 service results from seven compatible
runs over five calendar days, 19-23 July 2026. Repeated intraday runs are
retained. Earlier runs used two processors; they remain in commit-pinned bronze
and are rejected before silver.

The retained GPU input currently contains 3,121 benchmark-family prints,
including 887 H100 prints over 37 calendar days. Most early H100 prints had one
visible provider. Only 30 hourly prints on 23-24 July meet the current
10-provider comparison gate. The daily coverage table retains both eligible and
excluded history with an explicit reason.

## Source Hierarchy

The project prefers inputs in this order:

1. executed and verifiable transactions, when available under a usable data
   agreement;
2. executable offers with availability;
3. observed provider and marketplace offers;
4. official public rate cards;
5. archived rate cards and bounded observations;
6. clearly labeled expert assumptions.

The current H100 product is level 3: observed advertised offers. The current
sandbox product is levels 4 and 5: public and archived rate cards. Neither is
represented as a transaction benchmark.

This hierarchy follows the general data-sufficiency and transparency direction
in the [IOSCO Principles for Financial
Benchmarks](https://www.iosco.org/library/pubdocs/pdf/IOSCOPD415.pdf), but
Compute Bazaar does not claim IOSCO compliance or settlement-grade status.

Useful external reference points:

- [Ornn](https://data.ornn.com/faq) describes a volume-weighted index based on
  executed transactions. That is a stronger input class than the project
  currently possesses.
- [Silicon Data](https://www.silicondata.com/products/silicon-index) separates
  market segments, standardizes machine and rental terms, and publishes daily
  indices.
- [Compute Index](https://www.computeindex.dev/) explicitly labels its product
  as lowest advertised price and presents availability separately.

These products are not treated as interchangeable validation targets. Their
input classes, coverage, segmentation, and aggregation methods differ.

## Sandbox Rate Methodology

The normalized advertised rate is:

```text
processor quantity * processor rate per unit-hour
  + memory GiB * memory rate per GiB-hour
```

Eight services form the fixed 2026 comparison cohort:

```text
E2B, Daytona, Vercel, Novita, Modal, Runloop, Blaxel, Fly Sprites
```

At each actual cohort price-event date, the latest known quote for every member
is carried forward. A row is emitted only when all eight members are present.
The primary statistics are:

```text
headline       = median(normalized member rates)
dispersion     = p25 to p75 normalized member rates
secondary      = arithmetic mean(normalized member rates)
```

The median is less sensitive than the mean to one unusually expensive or cheap
rate card. The p25-p75 interval reports the middle half of the cross-section.
This follows the robust-statistics rationale documented by
[NIST](https://www.itl.nist.gov/div898/handbook/eda/section3/eda356.htm).
No member is silently removed as an outlier.

The current cross-section retains all 11 comparable services. It is shown
separately from the fixed cohort so new services can improve current discovery
without rewriting historical membership.

Each dated observation has one of these meanings:

- `effective`: the provider states when the rate took effect;
- `published`: the provider states when an update was published;
- `observed`: the date on which the quote was captured;
- `between_observations`: the quote changed between checks, so only the first
  later observation is known;
- `same_quote`: a later source review confirmed the same quote.

The gold `sandbox_price_events` table contains only actual price changes and
links every change to its evidence.

## One Workload Methodology

Same-job runtime is:

```text
sum of the ten published Better Auth mean task times
```

Estimated processor-and-memory cost is:

```text
runtime_seconds / 3600 * matching normalized hourly rate
```

The matching rate is the latest evidence at or before the run date. The
estimate excludes storage, network, plans, credits, retries, startup, teardown,
idle time, and work outside the ten tasks.

Gold retains all 38 raw service results. A second gold table summarizes each of
the six service variants:

```text
runtime       median, mean, p25, p75, minimum, maximum
cost          median, mean, p25, p75, minimum, maximum
provenance    result count, run count, first and latest run
frontier      lower-left non-dominated median runtime/cost points
```

The article therefore uses one price-performance scatter:

- circles are raw runs;
- diamonds are service medians;
- horizontal and vertical whiskers are the middle 50%;
- the dashed lower-left frontier identifies services not dominated on both
  median runtime and median estimated cost.

The frontier is descriptive, not a ranking of reliability, features, startup
latency, networking, security, or total bill.

## GPU and Sandbox Common Start

Compatible GPU input must satisfy:

```text
benchmark_family_id = H100
methodology_version = advertised_provider_floor_median_v1
benchmark_basis = advertised_hourly
provider_count >= 10
benchmark_usd_gpu_hr > 0
```

For each eligible hourly H100 print, the query carries forward the latest
fixed-cohort sandbox rate. The first eligible H100 timestamp is the common
start:

```text
gpu_base_100 =
  h100_observed_benchmark / first_eligible_h100_observed_benchmark * 100

sandbox_base_100 =
  sandbox_fixed_cohort_median / sandbox_median_at_common_start * 100
```

The H100 and sandbox p25-p75 bands are rebased by their respective starting
headline values. They are observed cross-sectional price dispersion, not
confidence intervals.

The price ratio is:

```text
sandbox_hours_per_h100_gpu_hour =
  h100_advertised_usd_per_gpu_hour / sandbox_median_usd_per_hour
```

The ratio is a rate-card comparison. It does not mean that one H100 GPU-hour and
that number of sandbox hours perform equivalent work.

The combined view can show:

- relative advertised-rate movement after broad H100 coverage begins;
- cross-sectional price dispersion;
- contributing-provider coverage;
- the price ratio between the two normalized hourly rates.

It cannot show:

- executed transaction prices or traded volume;
- demand, utilization, or causality;
- equal compute performance;
- a full customer invoice;
- a settlement-ready benchmark.

Sandbox concurrency can affect GPU utilization in reinforcement-learning
systems. Modal describes environment throughput as a way to
[keep GPUs fed](https://modal.com/blog/reinforcement-learning-infrastructure-problem).
That engineering relationship is not measured by this dataset. Modal's
millions-per-day claim, E2B's cumulative session claim, and Vercel's
deployment-per-day claim have different units and scopes. They are not combined
into a fabricated sandbox-volume series. Ornn documents a protected GPU
utilization endpoint, but licensed data has not been incorporated.

## Determinism and Validation

DataFusion-computed floats are canonicalized to 12 decimal places at the gold
boundary. Query text hashes, source rows, source metadata, target shape,
coverage gate, cohort membership, and precision are part of the build identity.
Identical inputs therefore produce the same build ID and publication JSON.

The pipeline fails on:

- unknown source or benchmark schema fields;
- missing required fields;
- duplicate observations;
- bad normalized-rate arithmetic;
- changed values for an existing immutable run;
- incompatible machine shapes;
- missing source-manifest files;
- missing GPU provenance fields;
- unknown allowlisted DataFusion query IDs.

## Commands

Validate reviewed evidence:

```sh
uv run sandbox-cost validate
```

Build from the maintained Parquet GPU history:

```sh
uv run sandbox-cost build \
  --output-root data/sandbox-cost \
  --dashboard-output-root data/dashboard/compute-bazaar \
  --gpu-history-ref data/sandbox-cost/silver/gpu_benchmark_history.parquet
```

The builder also accepts the public dashboard `benchmark-history.json` contract:

```sh
uv run sandbox-cost build \
  --output-root data/sandbox-cost \
  --dashboard-output-root data/dashboard/compute-bazaar \
  --gpu-history-ref data/dashboard/compute-bazaar/benchmark-history.json
```

Run an allowlisted query:

```sh
uv run sandbox-cost query \
  --output-root data/sandbox-cost \
  --query combined-common-start \
  --limit 25
```

Available IDs:

```text
hourly-prices
price-events
current-rates
fixed-rate
same-job-cost
same-job-summary
gpu-daily-coverage
gpu-eligible-history
combined-common-start
```

Fetch the public StarSling source without changing reviewed evidence:

```sh
uv run sandbox-cost refresh-benchmark \
  --output-root data/sandbox-cost \
  --source-ref main \
  --check
```

`--check` exits nonzero when compatible source evidence is new. Review the
commit-pinned bronze capture before running:

```sh
uv run sandbox-cost refresh-benchmark \
  --output-root data/sandbox-cost \
  --source-ref <reviewed-commit> \
  --update-evidence
```

Never combine `--check` and `--update-evidence`. A historical merge fails if a
source rewrites a known run.

## Recurrence

Windmill `market_hourly` builds GPU gold, exports benchmark history, builds
sandbox bronze/silver/gold, writes `sandbox-cost.json`, and publishes the market
run manifest each hour. The sandbox price evidence changes only after a manual
rate-card review; the workload evidence changes only after a reviewed
StarSling refresh.

`.github/workflows/sandbox-cost-sources.yml` runs daily and on demand. It
validates canonical evidence, fetches StarSling at a resolved commit, detects
source/schema drift or new compatible runs, and runs focused tests. A failed
check is a review request, not permission to publish new measurements.

Public price pages do not expose one stable, semantically equivalent API.
Manual review is therefore intentional:

1. Open every current source URL.
2. Verify billing basis, shape conversion, currency, and date meaning.
3. Add an immutable observation. Do not replace history.
4. Run validation, focused tests, and a deterministic build.
5. Inspect the rate event, current-rate row, chart, table, and source link.
6. Publish only after the methodology or cohort implications are reviewed.

## Publication

The public-safe artifact is:

```text
dashboard/compute-bazaar/sandbox-cost.json
```

The public AdamSioud article prefers the configured CloudFront URL and falls
back to its checked-in `exemplars/compute/sandbox-cost.json`. Localhost and
`file:` previews intentionally prefer the checked-in artifact so visual QA does
not silently read an older CDN object.

Article sources:

```text
external/AdamSioud/exemplars/compute/feeling_the_compute.html
external/AdamSioud/exemplars/compute/sandbox-cost.js
external/AdamSioud/exemplars/compute/sandbox-cost.json
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

Browser QA must cover:

- desktop and mobile layout;
- no page-level horizontal overflow;
- rate, workload, combined, and coverage charts;
- pointer and keyboard tooltips;
- Safari/CSS-zoom pointer alignment;
- all 33 price observations and 38 workload results;
- current-rate, rate-event, benchmark-run, and methodology links;
- browser console errors.
