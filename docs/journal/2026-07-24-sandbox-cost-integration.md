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
- Confirmed 38 provider-batch mean results from seven comparable public source
  batches over five calendar days, 19-23 July 2026.
- Re-extracted the latest source batch at replicate level: 69 individual jobs
  across six service variants and 690 retained task-phase samples.
- Confirmed every accepted run uses 4 vCPU, 8 GB memory, and 40 GB disk.
- Confirmed earlier Better Auth runs used 2 vCPU and are incompatible.
- Verified that all 38 canonical results reproduce from the public repository.
- Audited 3,121 retained GPU benchmark-family rows. H100 contributes 887 prints
  over 37 calendar days.
- Found that most June and early July H100 history had one provider. Only 25
  hourly prints on 23-24 July have at least 10 contributing providers.

## Methodology Audit, 25 July 2026

The first article pass used the phrase “38 raw runs.” That was wrong. Each of
those rows is a provider-batch summary produced by summing ten published task
means. The source's latest batch also exposes aligned replicate indices, which
allow reconstruction of actual individual jobs without pairing unrelated task
samples.

The corrected evidence hierarchy is:

```text
690 phase samples
  -> 69 individual jobs in the latest batch
  -> 6 latest service distributions

38 provider-batch means
  -> 7 source batches over 5 days
  -> 6 harness methodology generations
```

Additional source findings:

- the Better Auth app commit and ten task signatures are stable across all
  retained batches;
- six source harness commits produced the seven batches, so historical points
  are methodology-stratified context rather than one smooth time series;
- the measured runtime sums ten isolated task phases, not sandbox lifecycle or
  client-visible wall-clock time;
- two lint tasks include unmeasured preparation steps in the source harness;
- target and observed machine shapes differ by provider, especially disk, and
  now remain separate fields;
- the source contains no lifecycle metrics in these Better Auth run records,
  even though current StarSling methodology supports lifecycle as a separate
  suite;
- the Modal adapter requests four `cpu` units. Modal documents that unit as a
  physical core and bills the higher of request or actual usage. The earlier
  normalization priced two units and understated the audited request. The
  canonical rate evidence now prices all four requested units.

External review reinforced the correction:

- SPEC Cloud reports provisioning time separately from workload performance;
- SeBS separates benchmark, provider, and client time, and distinguishes cold
  and warm execution;
- reproducible cloud benchmark guidance emphasizes explicit measures,
  repeated experiments, technical artifacts, and claim reproducibility;
- NVIDIA DCGM exposes job-window GPU activity and power metrics, but nothing in
  the current sandbox price/runtime data can substitute for that telemetry.

The publication contract is now:

```text
latest workload claim
  descriptive observed-batch comparison
  all jobs + median + p25-p75

cost claim
  marginal processor-and-memory rate-card estimate
  not observed bill

history claim
  dated provider-batch context
  no connecting line across harness revisions

GPU/sandbox claim
  relative advertised-price movement only
  no demand, volume, utilization, or causal inference
```

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
5. The marginal measured-phase estimate uses processor and memory only because
   those are the comparable public rates in the current evidence.
6. The hourly sandbox headline is the median of a fixed eight-service cohort.
   P25-p75 is the primary spread; the arithmetic mean remains secondary.
7. The primary workload view keeps every latest individual job and summarizes
   each service with median measured phase time and p25-p75. Historical provider-batch
   means remain separately auditable and are not connected across harness
   revisions.
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
  audited requested processor quantity * processor unit rate
  + 8 GiB * memory GiB rate

fixed-cohort headline =
  median(hourly price for the same eight services)

marginal measured-phase processor-and-memory estimate =
  measured_phase_seconds / 3600 * service hourly price

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
- `sandbox_workload_batch_history`
- `sandbox_workload_latest_replicates`
- `sandbox_workload_latest_phases`
- `sandbox_workload_phase_summary`
- `sandbox_workload_service_summary`
- `gpu_h100_daily_coverage`
- `gpu_h100_eligible_history`
- `sandbox_gpu_cpu_common_start`

The public payload is `sandbox_cost_gold_v3`.

## V2 Reproducibility Record (Superseded)

The earlier deterministic build against the maintained GPU Parquet history
produced build ID `sandbox-cost-7248f5de0415d3f2` with:

- 33 sandbox price observations
- 10 actual price-change events
- 11 current service rates
- 4 fixed-cohort event rows
- 38 historical provider-batch means
- 69 latest individual jobs
- 690 latest phase samples
- 60 service/phase summaries
- 6 latest service summaries
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
- “Public hourly price for four processors and 8 GiB of memory” shows the
  fixed-cohort median, p25-p75 band, mean, all current rates, actual changes,
  and the complete audit table without claiming CPU performance equivalence.
- “Active task time measured; marginal compute cost estimated” separates the
  latest 69-job distribution, 690 phase samples, and 38 historical batch means.
- “GPU and sandbox prices, rebased rather than blended” shows only eligible
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
- Startup, teardown, retries, unmeasured preparation, storage, network, plans,
  credits, and work outside the ten tasks are excluded from the marginal
  measured-phase estimate.
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

## V2 Release Gate (Superseded)

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

## V2 Live Verification (Superseded)

The final public article is:

```text
https://www.adamsioud.com/exemplars/compute/feeling_the_compute.html
```

The V2 HTML and `sandbox-cost.js?v=5` were byte-identical to AdamSioud commit
`0300eea`. CloudFront, the local dashboard export, and the checked-in article
fallback all had SHA-256
`eb5e3677d8833b8b4da497ce061817def006e3d6d596a1613e7828df4bd966d8`.

Final browser checks used 1280 x 720 and 390 x 844 viewports:

- build `sandbox-cost-7248f5de0415d3f2` rendered from the public data URL;
- all four V2 D3 charts rendered within the article column;
- mobile document overflow was zero, while wide audit tables scrolled only
  inside their wrappers;
- the public payload exposed 11 rate cards, 10 change events, 33 price
  observations, six service summaries, 38 provider-batch means, and 30
  eligible H100 prints;
- the benchmark section had 105 HTTPS or internal-anchor links, with no empty
  or insecure link;
- pointer tooltips remained inside the viewport and keyboard arrows/Home/End
  updated `aria-valuetext`;
- desktop and mobile browser consoles contained no warnings or errors.

## V3 Runtime and Metering Audit (25 July 2026)

The V2 result was useful, but the phrase “active task time” was too broad. A
line-by-line audit of StarSling commit
`c7c9abf328430e2b5a01b0a4f57863c0fdd87641` found that
`realworld-runner.sh` records guest wall time with `date +%s%N` inside ten
selected windows. Clone and cold install include network and registry waits.
Most steady-state tasks run an unmeasured warm-up, and two lint tasks can run
unmeasured preparation. Startup, teardown, harness transport, and other work
between the windows remain outside the sum.

Decision:

- Public wording is now **measured phase time**.
- It is not labeled CPU time, CPU utilization, lifecycle latency, or billed
  duration.
- The marginal estimate still multiplies only those measured seconds by the
  matching public processor-and-memory rate.
- A future lifecycle study stays separate and should use monotonic client and
  guest clocks around create, ready, workload, and teardown boundaries.

The upstream matrix documents 12 fresh-sandbox replicates for the real-world
suite. The latest aggregate exposes 72 provider-and-replicate slots across six
service variants. Sixty-nine slots contain all ten aligned task measurements:

```text
Blaxel       11 / 12
Daytona VM   11 / 12
E2B          12 / 12
Modal gVisor 11 / 12
Modal VM     12 / 12
Novita       12 / 12
```

The three incomplete slots are no longer hidden behind an `n=69` headline.
DataFusion computes complete, source-slot, incomplete, and completion-ratio
fields for every service summary. No missing runtime is imputed. The source
records an explicit Daytona sandbox-create failure; the aggregate does not
attach a per-slot reason to each of the other two missing indices, so the
article does not invent one.

The adapter audit also confirmed that the replicate index identifies one fresh
sandbox for the suite, so summing ten task samples with the same provider and
replicate index is a defensible complete-job reconstruction.

## V3 Rate-Card Audit

All 11 current official sources were re-opened on 25 July 2026. The retained
24 July quotes and arithmetic still match the pages, so no duplicate
same-price observation was appended merely to make the history look newer.

The audit found a presentation issue rather than a price error: providers do
not meter the one-hour scenario identically. Silver and gold now add
`processor_meter`, `memory_meter`, and a plain `billing_basis_label`.

- E2B, Daytona, Novita, Runloop, Freestyle, and Beam price capacity while the
  sandbox or VM is running.
- Vercel prices active CPU and provisioned memory.
- Modal bills the higher of requested or actual CPU and memory. Its audited
  adapter requests four `cpu` units, so the scenario retains four billable
  units even though Modal documents each as a physical core.
- Blaxel prices active runtime by allocated memory while CPU scales with that
  memory.
- Fly Sprites and Sailboxes meter actual CPU and memory use. Their plotted
  number is therefore explicitly a full-use, one-hour scenario.

Primary pages checked:

- [E2B pricing](https://e2b.dev/pricing)
- [Daytona pricing](https://www.daytona.io/pricing) and
  [billing states](https://www.daytona.io/docs/billing)
- [Modal sandbox pricing](https://modal.com/products/sandboxes) and
  [resource semantics](https://modal.com/docs/guide/sandbox-resources)
- [Novita sandbox pricing](https://novita.ai/docs/guides/sandbox-pricing)
- [Blaxel pricing](https://blaxel.ai/pricing)
- [Runloop pricing](https://runloop.ai/pricing)
- [Vercel pricing](https://vercel.com/pricing)
- [Beam pricing](https://www.beam.cloud/pricing)
- [Fly Sprites pricing](https://fly.io/sprites/)
- [Freestyle pricing](https://www.freestyle.sh/pricing)
- [Sailboxes general-access price card](https://www.sailresearch.com/blog/sailboxes-general-access)

The fixed-cohort line is now described as a rate-card scenario, not a universal
allocation invoice. That distinction is generated into the public payload and
shown beside each current quote.

## Research Decision

The present study is publishable as a descriptive snapshot, not as a provider
SLA or definitive ranking. Median and p25-p75 are appropriate for 11-12
complete jobs; p95 and tight confidence claims are not.

The next measurement should add a separate lifecycle experiment:

```text
client create request
  -> sandbox ready for first command
  -> pinned workload start
  -> pinned workload finish
  -> teardown complete
```

It should report provisioning, ready latency, workload wall time,
client-visible time, teardown, success rate, and observed billed duration when
an export exists. Cold, warm/pool-backed, and concurrent runs must be separate
treatments. Provider order should rotate across repeated time blocks. The
current Better Auth study remains intact rather than being retrofitted into
that stronger claim.

## V3 Release Verification (25 July 2026)

The audited V3 article and recurring pipeline were released through the real
public path.

Publication record:

- AdamSioud narrative and D3 commit: `7dcb1ff`
- AdamSioud byte-identical live fallback commit: `94b1dfd`
- worker image:
  `sha256:5e1dbbc661136e5fe507f7d9838d2c4a6bdbe950f4f723971e26db3315df2b8e`
- one-off Windmill run:
  `market-sandbox-v3-20260724T233448Z`
- observed at: 24 July 2026 at 23:35 UTC
- successful providers: 18; failed providers: 0
- `gold`, `dashboard_export`, and `sandbox_cost` checks: `ok`
- overall run status: `warning`, because normalization and frontier-coverage
  warnings remain visible instead of being promoted to success
- sandbox build: `sandbox-cost-943536372119ae75`
- public payload SHA-256:
  `1db83c1918f28f49e0b95bf445473fbea2fa49bc00e5879a070ae04506e37b75`
- CloudFront object version:
  `GntlAUQsJFdOjDDiJyJRH6K8bTHkvgx3`
- public data URL:
  `https://d3n0n6h709c83f.cloudfront.net/sandbox-cost.json`
- public article:
  `https://www.adamsioud.com/exemplars/compute/feeling_the_compute.html`
- schedule: `f/compute-bazaar/market_hourly_hourly`, enabled hourly in UTC
- clean scheduled-source CI:
  `https://github.com/gustofied/the-compute-bazaar/actions/runs/30134572437`,
  passed on `e9791e1`

The live product contains:

- 33 reviewed sandbox-rate observations and 10 actual price-change events
- 11 current rate cards with explicit processor and memory metering semantics
- 69 complete jobs from 72 source slots; no missing job is imputed
- 690 retained measured phases
- 38 provider-batch means from seven source batches over five calendar days
- 31 coverage-eligible H100 prints and 31 common-start comparison rows
- 37 retained H100 coverage days, including low-coverage days excluded from
  the public relative comparison

The freshly exported public GPU history was downloaded and passed back through
the local DataFusion build. It reproduced the same build ID and exact public
JSON bytes. The checked-in article fallback, local dashboard export, S3 object,
and CloudFront object therefore shared the SHA-256 above at release time.

Production browser verification used the normal desktop viewport and a mobile
viewport override. All five D3 charts rendered, the document had no horizontal
overflow, chart containers had no internal overflow, all 69 job rows and 38
batch rows remained present, and loading states were hidden. Keyboard focus on
the workload chart exposed an exact value such as `Modal gVisor median,
442.3s, 9.3c, 11 of 12 source slots complete`; its tooltip remained inside the
mobile viewport. The browser console was empty.

The worker image initially failed to build because old Docker build layers had
filled the dev host's 20 GiB root volume. The live worker was never replaced
during that failure. Removing only unused images and BuildKit cache recovered
space; active containers and volumes were untouched. The operational README
now records that recovery and the preferred registry-built production path.

The first clean CI attempt also exposed that `uv --locked` needs the public
`external/instinct-bench` workspace member. The workflow now initializes that
single public submodule explicitly. It does not attempt to fetch the separate
private AdamSioud submodule; article integration tests remain part of the local
release gate.

This release does not change the claim boundary. It is a descriptive,
source-linked developer-workload snapshot. It is not lifecycle latency,
provider SLA, tail latency, observed billing, transaction volume, GPU
utilization, or a causal GPU-demand model.
