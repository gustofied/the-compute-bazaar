# Sandbox Cost Benchmark

The sandbox-cost benchmark is a maintained Compute Bazaar data product used by
the AdamSioud Compute article. It answers three deliberately separate
questions:

1. What public processor-and-memory rate is quoted for the audited
   four-processor, 8 GiB sandbox request?
2. How long did one pinned software workload spend inside its measured phases,
   and what marginal processor-and-memory cost does that measured time imply?
3. How did a coverage-qualified H100 advertised-price benchmark and a fixed
   sandbox rate-card cohort move after one declared common starting point?

These are not interchangeable measurements. An advertised rate is not an
invoice. Measured phase time is not lifecycle latency or CPU-busy time. A
rate-card estimate is not an observed charge. Provider count is not volume. An
observed offer is not an executed transaction.

## Measurement Contract

The current public workload claim is intentionally narrow:

```text
workload
  pinned Better Auth commit and ten task arguments

allocation target
  four schedulable processors, 8 GiB memory, 40 GB disk

latest observation
  69 complete fresh-sandbox jobs from 72 source replicate slots
  11 or 12 complete jobs per service
  690 retained phase measurements

reported statistic
  every job, service median, and service p25-p75 range

measured clock
  guest wall time inside ten selected task windows sharing one replicate index

not measured
  startup, teardown, retries, queueing, client-visible latency,
  unmeasured task preparation, reliability, or billed duration
```

This is a descriptive observed-batch comparison. It is not an SLA, a
tail-latency study, or a universal provider ranking.

## Maintained Data Path

```text
official price pages + archived observations
  -> reviewed immutable price evidence

StarSling public benchmark repository
  -> commit-pinned source files
  -> workload, shape, sample, and schema validation

Compute Bazaar GPU benchmark history
  -> retained observed-offer prints and provider coverage

all compatible inputs
  -> bronze evidence
  -> silver normalized Parquet
  -> named DataFusion queries
  -> gold publication tables
  -> sandbox-cost.json
  -> AdamSioud D3 article
```

Canonical reviewed evidence lives under:

```text
src/the_compute_bazaar/sandbox_cost/evidence/
```

Runtime output below `--output-root` is:

```text
bronze/hourly-price-evidence.json
bronze/benchmark-evidence.json
bronze/source-manifest.json
bronze/hpc-sandbox-benchmarks/commit=<sha>/...

silver/sandbox_hourly_prices.parquet
silver/sandbox_benchmark_batches.parquet
silver/sandbox_benchmark_replicates.parquet
silver/sandbox_benchmark_phases.parquet
silver/sandbox_benchmark_run_metadata.parquet
silver/gpu_benchmark_history.parquet

gold/sandbox_hourly_price_series.parquet
gold/sandbox_price_events.parquet
gold/sandbox_current_rates.parquet
gold/sandbox_fixed_rate.parquet
gold/sandbox_workload_batch_history.parquet
gold/sandbox_workload_latest_replicates.parquet
gold/sandbox_workload_latest_phases.parquet
gold/sandbox_workload_phase_summary.parquet
gold/sandbox_workload_service_summary.parquet
gold/gpu_h100_daily_coverage.parquet
gold/gpu_h100_eligible_history.parquet
gold/sandbox_gpu_cpu_common_start.parquet
gold/manifest.json
```

Bronze preserves source records, retrieval metadata, and checksums. Silver
standardizes units, machine shapes, timestamps, observation levels, timing
bases, and provenance. Gold contains publication-ready products computed by
named, hashed DataFusion queries.

## Price Evidence

The reviewed record contains 33 observations for 11 services from November
2024 through 24 July 2026. Every observation retains:

- original and archived URLs where available;
- observed, published, or provider-stated effective date;
- original processor billing unit and requested quantity;
- memory rate and normalized arithmetic;
- source class and a review note.

The public title says “four processors and 8 GiB” because that is the allocation
requested and observed by the audited benchmark adapters. It does not assert
that four CPU units are physically equivalent across vendors. CPU model,
architecture, isolation, burst policy, tenancy, and delivered work remain
different.

The normalized number is a one-hour comparison scenario, not one universal
billing contract. Silver and gold rows retain structured metering semantics:

- reserved meters price the requested capacity while the sandbox runs;
- active-use meters assume the stated processor or memory quantity is consumed
  for the full hour;
- Modal prices the higher of requested or actual use;
- Blaxel prices active runtime through allocated memory while CPU scales with
  that memory.

The article shows a plain billing-basis label beside every current quote. A
future rate revision must update both the arithmetic and its metering semantics.

This distinction matters for Modal. Modal documents `cpu` as physical cores and
bills by the higher of requested or actual usage. The audited StarSling adapter
passes four Modal CPU units for the benchmark target, so the evidence prices
four requested units rather than silently rewriting the adapter request as two.
See [Modal sandbox resources and
pricing](https://modal.com/docs/guide/sandbox-resources).

The normalized advertised rate is:

```text
processor quantity * processor rate per unit-hour
  + memory GiB * memory rate per GiB-hour
```

It excludes storage, network, subscription plans, credits, minimum billing
increments, idle retention, and provider-specific discounts.

## Fixed Rate-Card Cohort

Eight services form the fixed 2026 cohort:

```text
E2B, Daytona, Vercel, Novita, Modal, Runloop, Blaxel, Fly Sprites
```

At each actual price-event date, the latest known quote for every member is
carried forward. A row is emitted only when all eight members are present:

```text
headline       median(normalized member rates)
dispersion     p25 to p75 normalized member rates
secondary      arithmetic mean(normalized member rates)
```

The median reduces sensitivity to one unusually high or low rate card. The
p25-p75 interval reports the middle half of the cross-section. No service is
silently discarded as an outlier. The 11-service current cross-section is
published separately so discovery can expand without rewriting cohort history.

Date meanings remain explicit:

- `effective`: the provider states when the rate took effect;
- `published`: the provider states when the update was published;
- `observed`: the date on which a source review found the quote;
- `between_observations`: only the first later observation is known;
- `same_quote`: a later review confirmed the unchanged quote.

## Workload Evidence Levels

The StarSling source is pinned to commit
`c7c9abf328430e2b5a01b0a4f57863c0fdd87641`. The accepted Better Auth
workload keeps the same app commit, ten task IDs, task arguments, and target
shape.

The retained evidence has three levels:

### Phase

The latest source batch exposes 690 retained task samples:

```text
6 service variants
* 11 or 12 complete replicate-indexed sandboxes
* 10 task phases
```

Phase rows let the article show whether clone, install, build, lint, or
type-check work dominates. A displayed phase share is descriptive: the phase
median divided by the sum of the ten phase medians for that service.

### Individual job

An individual job is reconstructed only when all ten task metrics have the same
upstream replicate index. The duration is wall time inside each selected phase,
not CPU utilization:

```text
measured_phase_seconds(job) =
  sum(ten task samples with the same provider and replicate index)
```

The extractor rejects missing, duplicate, or misaligned task indices. The
latest batch exposes 12 source replicate slots per service, or 72 total. It
contains 69 complete jobs; three slots have no complete ten-phase result and are
not imputed. These rows power the primary runtime distribution and the service
median/p25/p75 summaries.

The ten windows do not all measure the same resource. Clone and cold install
include network and registry wait. Build, lint, and type-check are mostly local
work, but two lint tasks have unmeasured preparation and most steady-state tasks
have an unmeasured warm-up. This is a developer-workload comparison, not a pure
CPU benchmark.

### Provider-batch mean

The public source currently retains seven compatible batches over five calendar
days, 19-23 July 2026. They contain 38 provider-batch means:

```text
batch_active_seconds =
  sum(ten published task means)
```

Repeated intraday batches remain distinct. The seven batches use six upstream
harness commits. The Better Auth app and task signature stayed pinned, but a
harness change is still a methodology boundary. The article therefore draws no
continuous trend line across different methodology IDs. Earlier two-processor
runs remain in commit-pinned bronze and are rejected before silver.

## Statistical Treatment

The latest comparison publishes:

- all 69 complete individual jobs;
- 69-of-72 completion accounting;
- median measured phase time per service;
- p25-p75 measured phase time per service;
- minimum, maximum, and arithmetic mean in the gold table;
- the same descriptive summaries for the marginal cost estimate.

With 11-12 complete jobs per service, medians and interquartile ranges are useful
descriptions. The sample is too small for a stable p95, SLA claim, or narrow
confidence-bound ranking. No outlier is removed.

This follows the general direction of reproducible cloud benchmarking:

- [StarSling's methodology](https://github.com/starslingdev/hpc-sandbox-benchmarks/blob/c7c9abf328430e2b5a01b0a4f57863c0fdd87641/docs/methodology.md)
  separates between-sandbox replicates from within-sandbox passes and treats
  lifecycle as its own dimension.
- [SeBS](https://spcl.inf.ethz.ch/Publications/.pdf/sebs_middleware_21.pdf)
  separates benchmark, provider, and client times, distinguishes cold and warm
  execution, retains variation, and sizes samples against non-parametric
  confidence intervals.
- [SPEC Cloud IaaS](https://open.spec.org/cloud_iaas2016/docs/faq/faq.html)
  treats provisioning time as a separate cloud metric.
- The [Methodological Principles for Reproducible Performance
  Evaluation](https://atlarge-research.com/pdfs/TSE_2018_Cloud_Benchmarking_Methodology.pdf)
  emphasize technical reproducibility, explicit measures, repeated
  experiments, and claim reproducibility under opaque cloud variation.

The current result is deliberately presented below those stronger inferential
standards rather than borrowing their language without their sample design.

## Marginal Compute Estimate

For every retained job or batch:

```text
estimated_processor_and_memory_cost =
  measured_phase_seconds / 3600
  * matching_public_hourly_rate
```

The matching rate is the latest reviewed evidence at or before the benchmark
date. The estimate is a marginal rate-card model. It is not the provider's
observed bill and does not include:

- sandbox startup or teardown;
- queueing, retries, or failed attempts;
- unmeasured preparation around two lint tasks;
- storage, network, plans, credits, or minimum billing;
- idle retention or the difference between requested and actual usage.

The public article uses “marginal estimate,” not “job cost,” for this reason.

## Lifecycle V2

The next runtime experiment should remain separate from the measured-phase
study.
For each fresh sandbox and provider it should record:

```text
t0  client sends create request
t1  create call resolves
t2  first command is ready
t3  pinned workload begins
t4  pinned workload ends
t5  teardown request completes

provisioning latency    t2 - t0
workload wall time      t4 - t3
client-visible time     t4 - t0
teardown latency        t5 - t4
success rate            successful jobs / attempted jobs
observed billed time    provider billing export, when available
```

Cold and warm/pool-backed execution must be separate experiments. Concurrency
must be an explicit treatment, not an incidental side effect. Runs should pin
region, image, workload commit, task arguments, requested shape, adapter
version, and harness commit. Provider order should be rotated or randomized
across repeated time blocks to reduce time-of-day confounding.

The first publication can remain descriptive. A stronger ranking should add
enough independent batches under one methodology to report uncertainty around
the median and to study between-batch variation.

## GPU and Sandbox Common Start

Compatible GPU input must satisfy:

```text
benchmark_family_id = H100
methodology_version = advertised_provider_floor_median_v1
benchmark_basis = advertised_hourly
provider_count >= 10
benchmark_usd_gpu_hr > 0
```

For each eligible hourly H100 print, DataFusion carries forward the latest
fixed-cohort sandbox rate. The first eligible H100 timestamp is the base:

```text
gpu_base_100 =
  h100_observed_benchmark / first_eligible_h100_observed_benchmark * 100

sandbox_base_100 =
  sandbox_fixed_cohort_median / sandbox_median_at_common_start * 100
```

Each p25-p75 band is rebased by its own headline value. The bands are
cross-sectional price dispersion, not confidence intervals. Raw GPU dollars
and sandbox dollars are never placed on one axis.

This exploratory view can show relative advertised-price movement, dispersion,
coverage, and the ratio of the two hourly rate cards. It cannot show executed
transactions, demand, capacity, volume, utilization, causality, equal work, or
a full customer invoice.

Sandbox throughput could affect GPU utilization in a controlled agent or
reinforcement-learning workload, but this dataset cannot test that hypothesis.
A future experiment should hold the model, GPU, and request mix fixed; vary
sandbox concurrency; and record queue time, completions, failures, plus
[NVIDIA DCGM](https://docs.nvidia.com/datacenter/dcgm/latest/user-guide/feature-overview.html)
SM activity, tensor activity, memory activity, and power over the same job
window. Provider scale claims are not substituted for those measurements.

## Evidence Hierarchy

The project prefers inputs in this order:

1. executed and verifiable transactions under a usable data agreement;
2. executable offers with current availability;
3. observed provider and marketplace offers;
4. official public rate cards;
5. archived rate cards and bounded observations;
6. clearly labeled assumptions.

The current H100 product is level 3. The sandbox rate product is levels 4 and
5. Neither is represented as a transaction benchmark.

Reference products are not treated as interchangeable targets:

- [Ornn](https://data.ornn.com/faq) describes a volume-weighted index based on
  executed transactions.
- [Silicon Data](https://www.silicondata.com/products/silicon-index) separates
  market segments and standardizes machine and rental terms.
- [Compute Index](https://www.computeindex.dev/) labels lowest advertised
  prices and availability separately.

## Determinism and Validation

DataFusion-computed floats are canonicalized to 12 decimal places at the gold
boundary. Query hashes, source rows, source metadata, shape, cohort membership,
coverage gate, and precision are part of the build identity.

The pipeline fails on:

- unknown source or benchmark fields;
- missing required fields;
- duplicate observations;
- bad rate arithmetic;
- changed values for an existing immutable source run;
- incompatible requested machine shapes;
- implausible observed processor or memory shapes;
- missing, duplicate, or misaligned replicate task samples;
- phase totals that do not reproduce individual jobs;
- job means that do not reproduce source batch means;
- workload app, task argument, signature, or methodology drift;
- missing source-manifest captures;
- missing GPU provenance fields;
- unknown allowlisted DataFusion query IDs.

## Commands

Validate reviewed evidence:

```sh
uv run sandbox-cost validate
```

Build from maintained GPU history:

```sh
uv run sandbox-cost build \
  --output-root data/sandbox-cost \
  --dashboard-output-root data/dashboard/compute-bazaar \
  --gpu-history-ref data/sandbox-cost/silver/gpu_benchmark_history.parquet
```

Run an allowlisted DataFusion query:

```sh
uv run sandbox-cost query \
  --output-root data/sandbox-cost \
  --query workload-latest-replicates \
  --limit 25
```

Available query IDs:

```text
hourly-prices
price-events
current-rates
fixed-rate
workload-batch-history
workload-latest-replicates
workload-latest-phases
workload-phase-summary
workload-summary
gpu-daily-coverage
gpu-eligible-history
combined-common-start
```

Check the public StarSling source without changing reviewed evidence:

```sh
uv run sandbox-cost refresh-benchmark \
  --output-root data/sandbox-cost \
  --source-ref main \
  --check
```

`--check` exits nonzero when compatible evidence is new. Review the
commit-pinned bronze capture before promotion:

```sh
uv run sandbox-cost refresh-benchmark \
  --output-root data/sandbox-cost \
  --source-ref <reviewed-commit> \
  --update-evidence
```

Never combine `--check` and `--update-evidence`. Historical source rewrites
fail instead of silently changing prior observations.

## Recurrence

Windmill `market_hourly` builds GPU gold, exports benchmark history, rebuilds
the sandbox product, writes `sandbox-cost.json`, and publishes the market-run
manifest each hour. Reviewed sandbox rates change only after a manual source
audit. Workload evidence changes only after a reviewed StarSling promotion.

`.github/workflows/sandbox-cost-sources.yml` runs daily and on demand. It
validates evidence, resolves StarSling to an immutable commit, detects
source/schema drift or new compatible runs, and runs focused tests. A failed
source check is a review request, not permission to publish.

Manual price review is intentional:

1. Open the current and archived source URLs.
2. Verify billing unit, requested quantity, memory basis, currency, and date
   meaning.
3. Append an immutable observation; never replace history.
4. Validate, build, and run focused tests.
5. Inspect the event, current-rate row, chart, table, and source link.
6. Publish only after reviewing methodology and cohort effects.

## Publication and Verification

The public-safe artifact is:

```text
dashboard/compute-bazaar/sandbox-cost.json
```

The AdamSioud article prefers CloudFront in production and keeps a checked-in
fallback for local and failure-safe rendering:

```text
external/AdamSioud/exemplars/compute/feeling_the_compute.html
external/AdamSioud/exemplars/compute/sandbox-cost.js
external/AdamSioud/exemplars/compute/sandbox-cost.json
```

Focused verification:

```sh
uv run python -m unittest \
  tests.test_sandbox_cost \
  tests.test_adamsioud -v

node --check external/AdamSioud/exemplars/compute/sandbox-cost.js
```

Browser QA must cover desktop and mobile layout, no page-level horizontal
overflow, pointer and keyboard tooltips, Safari/CSS-zoom pointer alignment,
all price and workload audit rows, source links, fallback behavior, and browser
console/network errors.

Public page:

```text
https://www.adamsioud.com/exemplars/compute/feeling_the_compute.html
```
