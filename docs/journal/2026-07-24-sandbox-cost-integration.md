# Sandbox Cost Integration Journal

Date: 24 July 2026

## Objective

Promote the sandbox-cost research package into the maintained Compute Bazaar
lake and the real AdamSioud Compute article. Preserve source provenance, retain
all comparable benchmark runs, add an honest GPU comparison, and make the
result recur without pretending unstable price pages are automatic feeds or
provider coverage is transaction volume.

## Source Audit

- Read the handoff `README.md` and `SOURCES.md` before implementation.
- Confirmed 33 hourly-price observations across 11 services.
- Confirmed the fixed 2026 cohort has eight unchanged members.
- Audited the public StarSling index, methodology, and matching run files at
  commit `c7c9abf328430e2b5a01b0a4f57863c0fdd87641`.
- Confirmed 38 service results from seven comparable public runs over five
  calendar days, 19-23 July 2026.
- Confirmed every accepted run uses 4 vCPU, 8 GB memory, and 40 GB disk.
- Confirmed earlier Better Auth runs used 2 vCPU and are incompatible.
- Verified that all 38 canonical results reproduce from the public repository.
- Audited 3,121 retained GPU benchmark-family rows. H100 contributes 887 prints
  over 37 calendar days.
- Found that most June and early July H100 history had one provider. Only 25
  hourly prints on 23-24 July have at least 10 contributing providers.

## External Methodology Review

- Ornn describes a volume-weighted index built from executed transactions and
  a screened provider network.
- Silicon Data describes standardized market segments, daily calculation, and
  broader market-data validation.
- Compute Index clearly separates lowest advertised price from availability
  and coverage.
- IOSCO benchmark principles emphasize data sufficiency, hierarchy,
  methodology, and transparency. Compute Bazaar does not claim compliance.
- NIST guidance supports median and interquartile range as robust descriptive
  summaries.
- Modal documents millions of sandbox executions and explains why sandbox
  throughput can help keep GPUs fed in reinforcement-learning systems.
- E2B, Modal, and Vercel publish activity claims with different units, scopes,
  and time windows. They cannot be combined into a defensible volume series.
- No licensed transaction-volume or GPU-utilization series is present in this
  repository. Provider count is therefore reported only as coverage.

## Decisions

1. Versioned evidence lives inside the Python package so builds and CI do not
   depend on ignored local CSV files.
2. Raw public benchmark files are captured under a commit-pinned bronze prefix.
3. Existing observations are immutable. A refresh that changes a known result
   fails instead of rewriting history.
4. Benchmark results keep exact timestamps and repeated intraday runs.
5. The same-job estimate uses processor and memory only because those are the
   comparable public rates in the current evidence.
6. The hourly sandbox headline is the median of a fixed eight-service cohort.
   P25-p75 is the primary spread; the arithmetic mean remains secondary.
7. The workload view keeps every raw run and summarizes each service with
   median runtime, median estimated cost, IQR, and a descriptive lower-left
   frontier.
8. The GPU/sandbox comparison keeps all GPU history for coverage inspection but
   uses only H100 prints with at least 10 providers in the public common-start
   series.
9. Windmill rebuilds publication data hourly from reviewed evidence. A daily
   source check detects new benchmark runs. Public price pages remain a
   reviewed input.
10. The article reuses the existing D3 and Safari CSS-zoom pointer conventions
    instead of introducing another chart framework.

## Discarded Approaches

- The earlier 882-point H100 line was rejected. It connected low-coverage
  one-provider observations to current broad-coverage prints and overstated
  historical comparability.
- A raw GPU-price and sandbox-job-cost axis was rejected because the units and
  products are different.
- A sandbox “volume” or GPU-utilization line was rejected because public
  provider claims use incompatible units and do not form a common time series.
- A causal claim that sandbox price changes explain GPU utilization was
  rejected. Sandbox throughput can be operationally related to GPU-fed agent
  workloads, but the current data cannot estimate that relationship.
- A daily aggregate of the public benchmark was rejected because it would erase
  repeated intraday runs.
- Automatic scraping of all price pages was rejected because their billing
  semantics and markup are not stable enough to publish without review.
- A second standalone article was rejected. The benchmark belongs in the
  existing Tinkering narrative and maintained project pipeline.

## Formulas

```text
normalized hourly price =
  4 * processor unit rate
  + 8 GiB * memory GiB rate

fixed-cohort headline =
  median(hourly price for the same eight services)

same-job estimated processor-and-memory cost =
  runtime_seconds / 3600 * service hourly price

base-100 value =
  current compatible value / first eligible value * 100

hourly H100 eligibility =
  methodology_version = advertised_provider_floor_median_v1
  and benchmark_basis = advertised_hourly
  and provider_count >= 10
```

## Maintained Data Products

Bronze retains source records, source URLs, retrieval times, and checksums.
Silver stores parsed prices, machine shapes, units, exact run timestamps, and
matching decisions. Gold now contains:

- `sandbox_hourly_price_series`
- `sandbox_price_events`
- `sandbox_current_rates`
- `sandbox_fixed_rate`
- `sandbox_same_job_cost`
- `sandbox_same_job_summary`
- `gpu_h100_daily_coverage`
- `gpu_h100_eligible_history`
- `sandbox_gpu_cpu_common_start`

The public payload is `sandbox_cost_gold_v2`.

## Reproducibility Record

The full deterministic build against the maintained GPU Parquet history
produced build ID `sandbox-cost-7248f5de0415d3f2` with:

- 33 sandbox price observations
- 10 actual price-change events
- 11 current service rates
- 4 fixed-cohort event rows
- 38 same-job raw results
- 6 same-job summaries
- 37 retained H100 coverage days
- 30 eligible H100 hourly prints
- 30 common-start comparison rows

The first eligible H100 print is 23 July 2026 at 22:31 UTC: $2.695/GPU-hour,
10 providers, with the fixed sandbox cohort at $0.3496/hour. The last audited
print is 24 July 2026 at 22:00 UTC: $2.50/GPU-hour, 27 providers, with the fixed
sandbox cohort at $0.40356/hour. Both series are rebased to 100 at the first
eligible print.

## Frontend Integration

- Added one coherent sequence inside article point I, Tinkering.
- “Sandbox rates, normalized to one machine” shows the fixed-cohort median,
  p25-p75 band, mean, all current rates, actual changes, and the complete audit
  table.
- “Runtime measured, processor-and-memory cost estimated” separates measured
  runtime from the modeled cost formula and plots all 38 raw runs, service
  summaries, IQR whiskers, and the descriptive runtime/cost frontier.
- “GPU and sandbox rates from one honest starting point” shows only eligible
  H100 prints, the common-start rebasing, the latest rate ratio, and a separate
  37-day provider-coverage view.
- Source links sit beside the observations they support. The copy does not
  claim every plotted point is clickable.
- Charts support pointer inspection, keyboard focus, screen-reader status,
  responsive resizing, and the page’s Safari CSS-zoom coordinate correction.

## Visual QA

- Desktop inspection used 1280 x 720. All four D3 figures rendered, ledgers and
  tables stayed inside their containers, and the document had no horizontal
  overflow.
- Mobile inspection used 390 x 844. Charts resized to the content column, wide
  audit tables scrolled internally, and the page itself had no horizontal
  overflow.
- The open hourly-price audit retained all 33 rows.
- Pointer and keyboard inspection updated chart tooltips and accessible status
  text. Safari-style CSS zoom retained pointer alignment.
- The article exposes 11 current-rate source links, 10 price-event source
  links, and six workload-summary source links.
- Browser console inspection found no article warnings or errors.
- A production-like `0.0.0.0` preview encountered the stale public
  `sandbox_cost_gold_v1` object, rejected it by schema version, and rendered the
  checked-in v2 snapshot instead. This prevents an old hourly artifact from
  silently restoring the superseded comparison during deployment.

## Commands

```sh
uv run sandbox-cost validate

uv run sandbox-cost build \
  --output-root data/sandbox-cost \
  --dashboard-output-root data/dashboard/compute-bazaar \
  --gpu-history-ref data/sandbox-cost/silver/gpu_benchmark_history.parquet

uv run sandbox-cost query \
  --output-root data/sandbox-cost \
  --query combined-common-start \
  --limit 25

uv run sandbox-cost refresh-benchmark \
  --output-root data/sandbox-cost \
  --source-ref c7c9abf328430e2b5a01b0a4f57863c0fdd87641 \
  --check

uv run python -m unittest tests.test_sandbox_cost tests.test_adamsioud -v
node --check external/AdamSioud/exemplars/compute/sandbox-cost.js
```

## Data Caveats

- Four virtual processors are not metered identically by every service.
- Storage, network, plans, credits, retries, and work outside the ten tasks are
  excluded from estimated same-job cost.
- Observed dates are not silently relabeled as effective dates.
- A `between_observations` price point gives the first known later quote, not
  an invented exact change date.
- Seven matching benchmark runs are too short a history for broad performance
  claims.
- The 10-provider GPU gate is a transparent publication threshold, not a claim
  of settlement-grade representativeness.
- The GPU/sandbox chart compares relative advertised-rate movement. It does not
  measure demand, transaction volume, capacity, or utilization.

## Next Refresh

1. Review a failed scheduled source check or run `sandbox-cost
   refresh-benchmark --check`.
2. Inspect commit-pinned bronze captures and upstream methodology changes.
3. Use `--update-evidence` only with the reviewed commit.
4. Review public price pages and append observations without rewriting history.
5. Validate, build, run focused and full tests, then inspect the article.
6. Let the next hourly Windmill heartbeat publish `sandbox-cost.json`.

## Release Gate

The checked-in article and payload are release-safe because stale remote
schemas fall back to the local v2 snapshot.

The recurring release was exercised through the real VPC worker:

- AdamSioud article commits: `3f13535`, followed by live snapshot refresh
  `0300eea`
- worker image digest:
  `sha256:55bbe6f02dc4349f9cc64ad1f60170e1cd4321b991d7a8114b4421d89a8459de`
- one-off market run: `market-sandbox-v2-20260724T221553Z`
- observed at: 24 July 2026 at 22:16 UTC
- successful providers: 18; failed providers: 0
- `gold`, `dashboard_export`, and `sandbox_cost` checks: `ok`
- overall run status: `warning`, because provider normalization and coverage
  warnings remain visible rather than being promoted to success
- CloudFront artifact SHA-256:
  `eb5e3677d8833b8b4da497ce061817def006e3d6d596a1613e7828df4bd966d8`
- public data URL:
  `https://d3n0n6h709c83f.cloudfront.net/sandbox-cost.json`
- schedule: `f/compute-bazaar/market_hourly_hourly`, enabled hourly in UTC

A fresh local build from the newly exported public GPU history produced the
same build ID and byte-identical `sandbox-cost.json`.

## Live Verification

The final public article is:

```text
https://www.adamsioud.com/exemplars/compute/feeling_the_compute.html
```

The live HTML and `sandbox-cost.js?v=5` were byte-identical to AdamSioud commit
`0300eea`. CloudFront, the local dashboard export, and the checked-in article
fallback all had SHA-256
`eb5e3677d8833b8b4da497ce061817def006e3d6d596a1613e7828df4bd966d8`.

Final browser checks used 1280 x 720 and 390 x 844 viewports:

- build `sandbox-cost-7248f5de0415d3f2` rendered from the public data URL;
- all four D3 charts rendered within the article column;
- mobile document overflow was zero, while wide audit tables scrolled only
  inside their wrappers;
- the public payload exposed 11 rate cards, 10 change events, 33 price
  observations, six service summaries, 38 raw service results, and 30 eligible
  H100 prints;
- the benchmark section had 105 HTTPS or internal-anchor links, with no empty
  or insecure link;
- pointer tooltips remained inside the viewport and keyboard arrows/Home/End
  updated `aria-valuetext`;
- desktop and mobile browser consoles contained no warnings or errors.
