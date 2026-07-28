# Sandbox Cost Benchmark

The sandbox-cost benchmark is a maintained Compute Bazaar data product used by
the AdamSioud Compute article. It answers four deliberately separate
questions:

1. What do exact-shape public VM offers quote for four vCPUs and 8 GiB before a
   managed sandbox layer is added?
2. What public processor-and-memory rate is quoted for the audited
   four-processor, 8 GiB sandbox request?
3. How long did one pinned software workload spend inside its measured phases,
   and what marginal processor-and-memory cost does that measured time imply?
4. How did a coverage-qualified H100 advertised-price benchmark and a fixed
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

## Publication Rendering Contract

The benchmark is calculated before it reaches the article. The
`sandbox_cost_gold_v5` publication contract carries:

- every complete aligned job with its measured runtime and matching
  processor-and-memory cost estimate;
- one service summary with precomputed median, p25, and p75 values for both
  runtime and estimated cost;
- source-slot counts, incomplete-slot counts, source run IDs, and pinned source
  URLs;
- the retained cross-method batch history and phase summaries.

The article's JavaScript may choose the active measure, rank rows, set a scale,
and draw or label the published values. It does not calculate service medians,
percentiles, frontier membership, or cost estimates from raw browser rows. The
renderer accepts version 5 and fails visibly when the required workload
summary is absent or does not cover the same services as the constituent jobs.
This keeps the CLI, DataFusion tables, exported JSON, and article on one
statistical contract.

The public workload view defaults to median measured phase time and can switch
to median estimated processor-and-memory cost. Both values remain visible in
the ranked service ledger. Every complete job remains available as a plotted
observation and in the audit table; p25-p75 remains supporting dispersion.
Historical batches that cross harness generations stay in the collapsed audit
record rather than being drawn as one misleading performance series.

## Maintained Data Path

```text
exact public VM catalog APIs + ECB reference FX
  -> hourly immutable raw captures
  -> fixed exact-shape VM offer history

official sandbox price pages + archived observations
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
  -> sandbox-cost.json and sandbox/*.json card contracts
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

silver/vm_capacity/generations/run_id=<run>/...
silver/vm_discovery/generations/run_id=<run>/...
silver/_manifests/vm_capacity/latest.json
silver/_manifests/vm_discovery/latest.json

silver/generations/build_id=<build>/<table>.parquet
gold/generations/build_id=<build>/<table>.parquet
_manifests/sandbox_cost/date=<date>/build_id=<build>.json
_manifests/sandbox_cost/latest.json
gold/manifest.json
```

Bronze preserves source records, retrieval metadata, and checksums. Silver
standardizes units, machine shapes, timestamps, observation levels, timing
bases, and provenance. Gold contains publication-ready products computed by
named, hashed DataFusion queries. The latest manifests are the authoritative
catalog: agents and CLI queries follow their immutable table refs. Stable
silver/gold filenames are build staging aliases only and must not be used as
cross-run catalog pointers.

Each VM refresh holds a conditional S3 lease around its read/merge/publish
transaction. Manual and scheduled runs therefore cannot overwrite one
another's cumulative history. A successful run writes a new immutable
generation and updates its latest manifest last. Local runs use the same
contract with an operating-system file lock.

The VM source captures live below `--raw-root`:

```text
sandbox-cost/vm-capacity/provider=<provider>/date=<yyyy-mm-dd>/
  run_id=<vm-capacity-run>/...
```

Every hourly check gets a raw capture and checksum. Silver history stores one
normalized observation per successful source check, including hours when the
published price is unchanged. A repeated run for the same source and timestamp
is idempotent; a different payload for an already retained timestamp fails.
This is an observation series, not a change-event series.

## Underlying VM Capacity Cohort

The publication cohort is fixed and exact:

```text
cohort ID       public_vm_4vcpu_8gib_v2
shape           exactly 4 vCPU and 8 GiB memory
purchase basis  public Linux on-demand offer
headline        median USD hourly offer
dispersion      p25-p75 USD hourly offers
membership      fixed seven-vendor cohort
frequency       one point per complete hourly source check
history start   first automated observation; no invented backfill
```

The fixed members and source selections are:

| Provider | Exact offer | Reference location | Storage treatment |
| --- | --- | --- | --- |
| Akamai Linode | `g6-standard-4` | public global plan | 160 GB bundled |
| Vultr | `vc2-4c-8gb` | Paris (`cdg`) reference | 160 GB SSD bundled |
| Scaleway | `BASIC3-X4C-8G` / `fr-par-2` | Paris | storage separate |
| Microsoft Azure | `Standard_F4s_v2` | West Europe | 32 GiB temporary disk; OS and persistent disks separate |
| Amazon EC2 | `c7i.xlarge` | Paris (`eu-west-3`) | EBS storage separate |
| OVHcloud | `d2-8.consumption` | France public catalog | 50 GB local NVMe bundled |
| Oracle Cloud | `VM.Standard.E4.Flex`, 2 OCPU + 8 GB | global public list | boot and block volumes separate |

The sources are the official [Akamai Linode Types
API](https://techdocs.akamai.com/linode-api/reference/get-linode-types),
[Vultr Plans API](https://docs.vultr.com/reference/vultr-cli/plans/list),
[Scaleway Public Catalog
API](https://www.scaleway.com/en/developers/api/product-catalog/public-catalog),
[Azure Retail Prices
API](https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices),
[AWS Price List
API](https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_pricing_GetProducts.html),
[OVHcloud public
catalog](https://eu.api.ovh.com/console-preview/?section=%2Forder&branch=v1#get-/order/catalog/public/cloud),
and [Oracle public price
API](https://docs.oracle.com/en-us/iaas/Content/Billing/Tasks/signingup_topic-Estimating_Costs.htm).
Azure's machine shape is checked against the [Fsv2
specification](https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/compute-optimized/fsv2-series).
AWS is an exact Price List product and on-demand term. Oracle is composed from
two official PAYG OCPU meters and eight official PAYG memory-GB meters; on x86
Oracle shapes, two OCPUs correspond to four vCPUs.

Scaleway and OVHcloud are quoted in EUR. Each observation retains the native
price and the latest ECB EUR/USD reference rate used to produce its USD
comparison value. An FX move can therefore move the USD series even when the
native offer is unchanged.

The cohort rejects spot, reserved, promotional, and mismatched shapes. It is
not a CPU performance benchmark: vCPU generation, tenancy, burst policy,
network, and bundled storage differ. The article calls the values “observed VM
offer rates,” not a universal CPU price.

The original four-member cohort is retained as
`public_vm_4vcpu_8gib_v1`. It is not rewritten or backfilled after the
membership expansion. Cohort v2 begins at the first timestamp where all seven
exact vendor observations are present. The public chart uses v2; the v1 gold
table remains queryable for audit. In the public payload,
`observed_market_rate` and the compatibility alias `fixed_cohort_rate` follow
the active cohort; v1 rows are available only under
`legacy_fixed_cohort_rate`.

Akash is collected beside the cohort as a `marketplace_indication`. Its public
pricing endpoint returns a request-specific monthly model for four CPU units,
8 GiB memory, and 20 GiB storage. The pipeline divides that estimate by 730 to
show an hourly indication, but does not call it a vCPU offer, live bid, lease,
or executed price and does not include it in the seven-vendor median.

The current substrate comparison is:

```text
vm_observed_median[t] =
  median(seven exact-shape vendor offer USD/hour observations at t)

sandbox_fixed_median =
  median(current fixed sandbox cohort USD/hour)

observed_rate_ratio =
  sandbox_fixed_median / latest vm_observed_median
```

The ratio describes two public offer cohorts at one check time. It is not a
markup, gross margin, invoice, or like-for-like cost decomposition. Managed
sandbox rates can include orchestration, isolation, APIs, images, pooling,
support, and billing semantics that are absent from the VM offers.

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

## Publication Scope

The maintained data products are broader than the public article. The article
keeps one absolute VM/VPS-versus-sandbox rate view, one latest same-workload
cost distribution, one independently rebased H100/VM/sandbox comparison, and
one source-selectable rental-occupancy view. Current vendor offers and
historical provider-batch summaries remain available in collapsed audit
tables.

The young seven-vendor hourly VM series is not repeated as a standalone chart.
Instead, every unchanged hourly point appears in the absolute rate view and
the VM median appears in the relative-price view. The historical
provider-batch chart remains outside the main narrative because its 38 rows
cross six harness methodologies. Those rows remain queryable and auditable;
they have not been collapsed, averaged by day, or deleted.

This is a presentation decision, not a data-retention rule. A future frontend
can rebuild either view from gold, provided it preserves the cohort and
methodology boundaries documented here.

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

The public article uses “estimated processor-and-memory cost” and states the
formula beside the chart. It does not shorten that qualified estimate to a
provider bill or total job cost.

## Source-Run History

DataFusion builds one gold row per retained StarSling source run:

```text
sandbox_benchmark_batches
  group by benchmark_run_id
  -> sandbox_workload_run_history
```

Each row carries the original run timestamp and URL, source commit, task
signature, methodology ID, machine shape, distinct service count,
fixed-cohort completeness, and median/p25/p75 values for measured runtime and
estimated processor-and-memory cost. Repeated runs on the same calendar day
remain separate.

The current public source has seven matching four-processor runs over five
calendar days. Four early runs contain five service rows. Three later runs
contain all six fixed services and are eligible for the article headline:

```text
29937467891
29982453127
30019301067
```

No missing service is imputed. The incomplete source runs remain in the gold
table and public audit payload. The frontend may filter to
`fixed_cohort_complete = true`, but it does not recompute medians or collapse
intraday runs.

## Market Pulse Rendering

The article opens the maintained section with six separate panes:

```text
H100 observed benchmark | Akash available GPU share
seven-vendor VM median  | Akash available CPU share
StarSling job-cost median | StarSling measured-runtime median
```

H100 and VM panes use their precomputed gold medians and cross-sectional
p25-p75 bands. Akash panes use the published
`available_units / total_units` share and retain GPU units or CPU millicores as
reported. StarSling panes use only complete six-service source-run summaries.
Price, available share, estimated cost, and runtime never share an axis.

The default window is 1D, followed by 7D, 1M, and All. GPU, VM, and Akash
series are filtered against the latest live market observation. If no
compatible StarSling batch falls inside that live window, the latest source
point remains visible for context with its actual timestamp and an explicit
outside-window note. It is not copied forward or relabelled as hourly.

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

## GPU, VM, and Sandbox Relative Prices

Compatible GPU input must satisfy:

```text
benchmark_family_id = H100
methodology_version = advertised_provider_floor_median_v1
benchmark_basis = advertised_hourly
provider_count >= 10
benchmark_usd_gpu_hr > 0
```

For each eligible hourly H100 print, DataFusion carries forward the latest
fixed-cohort sandbox rate. The first eligible H100 timestamp is the base for
those two series:

```text
gpu_base_100 =
  h100_observed_benchmark / first_eligible_h100_observed_benchmark * 100

sandbox_base_100 =
  sandbox_fixed_cohort_median / sandbox_median_at_common_start * 100
```

The seven-vendor VM/VPS series begins later and uses its own first complete
hourly check:

```text
vm_base_100 =
  vm_seven_vendor_median / first_complete_vm_median * 100

vm_p25_base_100 =
  vm_seven_vendor_p25 / first_complete_vm_median * 100

vm_p75_base_100 =
  vm_seven_vendor_p75 / first_complete_vm_median * 100
```

These VM fields are built by the named DataFusion gold query and published in
`vm_capacity.observed_market_rate`; the browser does not derive them. Minimum
and maximum base-100 fields are retained for audit and the absolute-price
envelope. Each selected p25-p75 band is cross-sectional price dispersion, not
a confidence interval. Raw GPU, VM, and sandbox dollars are never placed on
one linear axis.

This exploratory view can show relative advertised-price movement, dispersion,
coverage, and different timing of observed rate changes. It cannot show
executed transactions, demand, traded volume, causality, equal work, or a full
customer invoice.

## Observed Rental Occupancy

Rental occupancy is published only when a source supplies a rented numerator
and matching rentable-population denominator:

```text
rented_share = rented_units / total_units
```

Akash reports GPU units. Clore reports public on-demand servers. Their units
are not pooled, averaged, or drawn as one market-wide line. The article uses
source tabs: the upper pane shows the selected rented share, while the lower
pane shows the matching rented and total counts. Those counts are observed
capacity, not trading volume. A statistical or Bollinger-style band is not
drawn because there is no cross-sectional distribution behind each occupancy
point.

Sandbox throughput could affect GPU utilization in a controlled agent or
reinforcement-learning workload, but this dataset cannot test that hypothesis.
A future experiment should hold the model, GPU, and request mix fixed; vary
sandbox concurrency; and record queue time, completions, failures, plus
[NVIDIA DCGM](https://docs.nvidia.com/datacenter/dcgm/latest/user-guide/feature-overview.html)
SM activity, tensor activity, memory activity, and power over the same job
window. Provider scale claims are not substituted for those measurements.

## Utilization Metric Contract

The word `utilization` is prohibited as an unqualified field name. The
maintained metric dictionary separates five stages:

```text
available -> rented -> allocated -> active -> productive
```

They answer different questions:

| Stage | Numerator | Denominator | Current Compute Bazaar coverage |
| --- | --- | --- | --- |
| Available | checks with an eligible rentable offer | scheduled checks | GPU and VM offer checks only |
| Rented | eligible units currently rented | eligible tracked population | Akash GPU units and Clore public on-demand servers, shown separately |
| Allocated | resource units assigned to workloads | schedulable units | not currently observed across providers |
| Active | time or cycles with a selected engine active | sampled time or cycles | not currently observed comparably |
| Productive | completed units meeting a declared objective | elapsed time | sandbox completions and runtime are retained, but no cross-provider SLO goodput is claimed |

[NVIDIA DCGM](https://docs.nvidia.com/datacenter/dcgm/latest/user-guide/feature-overview.html)
defines separate engine, SM, tensor, and DRAM activity metrics and warns that
occupancy alone does not prove effective use. [Amazon
EC2](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/burstable-credits-baseline-concepts.html)
defines CPU utilization against the compute units allocated to one instance.
[Kubernetes](https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/)
schedules against requests even when actual CPU or memory use is low.
[E2B](https://e2b.dev/docs/sandbox/metrics) exposes per-sandbox CPU, memory,
and disk samples, while [Modal](https://modal.com/docs/guide/sandbox-resources)
can bill the higher of requested and actual resource use. These are related
measurements, not interchangeable definitions.

The reviewed source register is
`src/the_compute_bazaar/sandbox_cost/evidence/utilization-methodology.json`.
Builds copy it into bronze, validate exact fields and source URLs, normalize
all definitions into
`silver/compute_utilization_metric_definitions.parquet`, and use DataFusion to
publish `gold/compute_utilization_public_ladder.parquet`. The public JSON marks
the result `methodology_only_no_observed_values`.

Any future observed utilization fact must retain at least:

```text
metric_id
numerator
denominator
window_start
window_end
sampling_interval
aggregation
resource_scope
source_type
methodology_version
```

An offer disappearing between polls is not evidence that it was rented. A
running lease is not evidence of processor activity. Processor activity is not
evidence that useful work met its latency or correctness objective.

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

- unknown or missing fixed-cohort VM providers;
- a VM offer that no longer matches exactly four vCPUs and 8 GiB;
- duplicate source observations at one timestamp or a current row without
  retained history;
- missing native currency, FX, storage, region, or source fields;
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

Check all live VM sources and retain their raw responses:

```sh
uv run sandbox-cost refresh-vm-capacity \
  --output-root data/lake/sandbox_cost \
  --raw-root data/raw

uv run sandbox-cost refresh-vm-discovery \
  --output-root data/lake/sandbox_cost \
  --raw-root data/raw
```

Build from maintained GPU and VM history:

```sh
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
```

Run an allowlisted DataFusion query:

```sh
uv run sandbox-cost query \
  --output-root data/lake/sandbox_cost \
  --query vm-observed-rate \
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
workload-run-history
vm-current
vm-fixed-rate
vm-expanded-current
vm-observed-rate
vm-marketplace-current
vm-discovery
vm-sandbox-current
gpu-daily-coverage
gpu-eligible-history
combined-common-start
relative-common-start
utilization-ladder
```

Check the public StarSling source without changing reviewed evidence:

```sh
uv run sandbox-cost refresh-benchmark \
  --output-root data/lake/sandbox_cost \
  --source-ref main \
  --check
```

`--check` exits nonzero when compatible evidence is new. Review the
commit-pinned bronze capture before promotion:

```sh
uv run sandbox-cost refresh-benchmark \
  --output-root data/lake/sandbox_cost \
  --source-ref <reviewed-commit> \
  --update-evidence
```

Never combine `--check` and `--update-evidence`. Historical source rewrites
fail instead of silently changing prior observations.

### Public Recurring Source Poll

The workload evidence comes from the maintained public
[StarSling repository](https://github.com/starslingdev/hpc-sandbox-benchmarks).
That upstream project owns provider SDK calls, sandbox lifecycle, the pinned
4-vCPU/8-GiB/40-GB target, replicate planning, task timing, and its validated
Run schema. Compute Bazaar does not dispatch or pay for benchmark runs. It owns
the market-data side:

```text
public committed StarSling Run document
  -> daily immutable Compute Bazaar bronze retrieval
  -> content-addressed workload silver generation
  -> next hourly DataFusion workload gold build
  -> sandbox-cost.json and article
```

Publish a compatible public source generation explicitly:

```sh
uv run sandbox-cost refresh-benchmark \
  --output-root data/lake/sandbox_cost \
  --source-repository OWNER/hpc-sandbox-benchmarks \
  --source-ref main \
  --publish-operational
```

Each poll writes a unique bronze capture with retrieval time and checksums:

```text
bronze/hpc-sandbox-benchmarks/
  source=<owner--repository>/commit=<sha>/refresh_id=<refresh>/...
```

Normalized tables are content-addressed, so polling an unchanged source does
not create a false benchmark observation:

```text
silver/workload_benchmark/generations/generation_id=<content-hash>/
silver/_manifests/workload_benchmark/polls/date=<date>/...
silver/_manifests/workload_benchmark/latest.json
```

Before promoting the latest generation, the refresh checks the exact target
shape, pinned workload version and ten-task signature, aligned replicate
indices, cost arithmetic, source-file checksums, and retained history. A source
cannot remove a reviewed run or change a prior result at the same identity.
The hourly sandbox build follows the latest manifest automatically and
recomputes the normal workload gold tables with the existing named DataFusion
queries.

The Windmill source poll is enabled by default:

```sh
uv run python infra/windmill/bootstrap_sandbox_benchmark_schedule.py
```

Use `--disabled` only to pause it intentionally. The poll uses no provider
credentials. Polling the same upstream commit records retrieval provenance but
reuses the same content-addressed silver generation, so it does not invent a
new runtime sample. Runtime history changes only after upstream publishes a new
compatible, schema-valid run.

## Recurrence

Windmill `market_hourly` checks the seven exact vendor inputs and the separate
Akash indication, retains every raw check, builds GPU gold, exports benchmark
history, rebuilds the sandbox product, writes `sandbox-cost.json`, and
publishes the market-run manifest each hour. One source failure is isolated and
reported as a warning while the last validated current row remains available.
Gold does not emit a new seven-vendor point for an incomplete hour. Reviewed
managed-sandbox rates change only after a manual source audit. External
StarSling evidence changes only when a new compatible public commit passes the
strict checks above; each methodology remains separately identified.

`.github/workflows/sandbox-cost-sources.yml` runs daily and on demand. It
validates evidence, performs a clean live schema/shape check for the four
unauthenticated v1 catalogs, resolves StarSling to an immutable commit, detects
source/schema drift or new compatible runs, and runs focused tests. The AWS
Price List input and the full seven-vendor cohort are checked by the
IAM-enabled Windmill worker each hour. The CI VM check writes only to `/tmp`;
Windmill owns durable hourly history. A failed source check is a review
request, not permission to publish.

`.github/workflows/public-feed-freshness.yml` checks CloudFront every hour and
fails when either the public snapshot or the latest complete seven-vendor VM
print is more than 2.5 hours old. It also fails on a partial VM source check.
The same check is available locally:

```sh
uv run sandbox-cost check-public \
  --url https://d3n0n6h709c83f.cloudfront.net/sandbox-cost.json \
  --max-age-hours 2.5
```

Manual managed-sandbox price review is intentional:

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
dashboard/compute-bazaar/sandbox/rates.json
dashboard/compute-bazaar/sandbox/workload.json
dashboard/compute-bazaar/sandbox/relative.json
```

The version 5 payload contains the public VM current cohort, hourly observed
history, current VM/sandbox comparison, managed-sandbox rate history, workload
results, GPU comparison, and the source-linked utilization metric dictionary.
Raw S3 refs and private manifests are removed at the public boundary. The
three split files use `compute_bazaar_card_v1`. `sandbox/relative.json` is built
from `gold/gpu_vm_sandbox_common_start.parquet` by the allowlisted
`relative-common-start` DataFusion query. The browser does not join or rebase
the component series.

The AdamSioud article prefers CloudFront in production and keeps a checked-in
fallback for local and failure-safe rendering:

```text
external/AdamSioud/exemplars/compute-bazaar/index.html
external/AdamSioud/exemplars/compute-bazaar/sandbox-cost.js
external/AdamSioud/exemplars/compute-bazaar/sandbox-cost.json
```

The browser does not derive benchmark values from provider rows. DataFusion
builds the gold median, mean, percentiles, and complete-hour history before the
sanitized JSON export is written. The article renders that public gold product.
Its dedicated VM chart uses the v2 observation window so consecutive hourly
checks remain distinguishable; the adjacent overview keeps the longer
VM-versus-sandbox time range for context.

The article also plots the normalized sandbox-provider rows behind the gold
median. A dot marks a series start or a changed public rate, while unchanged
retained observations remain available to pointer and keyboard inspection.
Each provider uses a step line between dated observations. The line means
"last observed public rate," not an hourly transaction print. Solid lines
identify the fixed eight-service cohort; dashed lines retain additional
observed services without letting them alter the fixed-membership median.

All article figures now use the shared D3 card contract documented in
`docs/visualization-system.md`. Each chart remains a view over the public gold
payload, but pointer or keyboard selection also publishes a persistent
observation with date, value, detail, and a source action when the row contains
a public URL. The shared helper owns Safari/CSS-zoom pointer geometry, tooltip
placement, card status, methodology links, and stable share links. It does not
calculate benchmark values.

Focused verification:

```sh
uv run python -m unittest \
  tests.test_sandbox_cost \
  tests.test_vm_capacity \
  tests.test_adamsioud -v

node --check external/AdamSioud/exemplars/compute-bazaar/sandbox-cost.js
```

Browser QA must cover desktop and mobile layout, no page-level horizontal
overflow, pointer and keyboard tooltips, Safari/CSS-zoom pointer alignment,
all price and workload audit rows, source links, fallback behavior, and browser
console/network errors.

Public page:

```text
https://www.adamsioud.com/exemplars/compute-bazaar/
```
