# Data Estate And Editorial Scope Journal

Date: 25 July 2026

## Why This Pass Happened

The article had accumulated four separate views around the VM and sandbox
work:

- a seven-vendor hourly VM-only chart;
- an expanded underlying-offer ledger;
- a latest-job runtime distribution;
- a historical provider-batch chart.

Each view was backed by real retained data, but the page gave internal audit
objects the same narrative weight as the public questions:

1. What does the requested capacity cost before and after the sandbox layer?
2. What is the estimated processor-and-memory cost of the same measured
   software job on each sandbox?
3. How did H100, VM/VPS, and sandbox advertised rates move relative to their
   own starting observations?
4. Where a source exposes both rented and total capacity, what share was
   rented and how large was the observed population?

The presentation had become an operator board inside an essay. The data layer
should remain broad; the public story should be selective.

## Data Audit

The maintained data estate is now recorded in
[`docs/data-inventory.md`](../data-inventory.md).

Evidence inspected during this pass:

- canonical sandbox validation reports 33 price observations across 11
  services;
- workload evidence contains 38 provider-batch summaries from seven public
  batches over five calendar days and six harness methodologies;
- the latest comparable source batch contains 69 complete jobs and 690 phase
  observations;
- the checked-in public payload contains all 38 historical summaries and all 69
  latest jobs;
- the hourly VM collector stores unchanged prices as new timestamped
  observations and protects existing identities from conflicting rewrites;
- the final public feed passed the 2.5-hour freshness check at
  `2026-07-25T21:06:58Z`; its latest complete VM observation was
  `2026-07-25T21:03:00Z`;
- the ignored local `data/lake` cache did not contain the newest expanded VM
  build, while the public/S3-backed projection was fresh.

The last point is important: local ignored data is convenient for development,
but S3 manifests and gold tables are operational truth. Publication JSON is a
projection, not a database.

## Editorial Decision

Keep in the main article:

- one VM-versus-managed-sandbox rate history;
- the current headline rates and ratio;
- one latest same-workload cost distribution;
- compact cost/rate summaries, with runtime and phase evidence disclosed;
- collapsed source and audit tables;
- the exploratory GPU/VM/sandbox relative series;
- source-selectable rental occupancy with matching capacity counts.

Demote from the main narrative:

- the separate flat, young seven-vendor VM-only chart;
- the historical provider-batch chart across six harness methodologies.

The VM offers remain available in one collapsed source inspection section. All
38 historical provider-batch rows remain in gold, the public payload, and the
collapsed audit table. No observation was deleted and no formula changed.

The workload chart is now titled “Estimated cost of the same job.” The
methodology copy still defines the measured phase precisely, but runtime is an
input and audit field rather than the headline.

## Data/Product Boundary

This pass adopts a durable rule:

```text
bronze/silver/gold may retain more than the article displays

article/dashboard/API selects views from gold

removing a chart never removes the source series

adding a chart never creates a browser-only metric
```

The seven-vendor hourly rate remains a useful young series. It now appears
inside the absolute VM/VPS-versus-sandbox chart and the relative-price chart,
but it does not receive a third standalone chart. Every unchanged hourly
observation remains queryable data.

The historical workload summaries should be visualized again only when the
query groups comparable harness methodologies or a controlled recurring
benchmark supplies a genuinely consistent time series.

## Workload Comparison Redesign

The first simplified workload view still privileged runtime: it drew all 69
jobs and showed estimated cents only as a label. The next pass added a
time/cost switch, but that still made the reader choose the article's actual
question. The final public view makes estimated processor-and-memory cost the
only headline measure. Runtime remains the measured input and audit evidence.

The revised primary view now:

- ranks six services by their published median cost estimate;
- retains all 69 complete jobs as dots and six medians as diamonds;
- shows the published p25-p75 cost range as the service whisker;
- places the matching public hourly rate beside each service estimate;
- retains every complete job for pointer and keyboard inspection;
- puts measured runtime in the tooltip and collapsed evidence table;
- leaves all 38 cross-method historical summaries in a collapsed audit table,
  outside the primary visualization.

No benchmark formula moved into the browser. Version 5 already contains every
job, service medians, p25-p75 values, and cost estimates produced by the
maintained DataFusion/gold build. The D3 code now refuses a missing or
service-incomplete workload summary instead of deriving a replacement from
the raw jobs. Its permitted work is presentation: sorting the published cost
values, scaling, labeling, and interaction.

The public copy was tightened around plain measurement terms:

```text
measured phase time
estimated processor-and-memory cost
complete job
service median
middle 50%
```

The section explicitly says that the latest batch has 69 complete jobs from 72
source slots, that three incomplete slots are not estimated, and that the
historical evidence crosses six harness revisions.

## Price And Capacity Redesign

The article now uses the first GPU price chart's interaction pattern without
copying its market assumptions:

- H100, VM/VPS, and sandbox median lines remain visible together.
- Each series begins at 100 at its own first retained observation.
- H100 and sandbox use the existing common-start gold table.
- VM/VPS base-100 median, p25, p75, minimum, and maximum are produced by the
  DataFusion VM gold query.
- Tabs select which middle-50% price band is emphasized.
- The absolute chart retains the full seven-offer VM envelope as a lighter
  band and the middle 50% as the darker band.

The rental-occupancy chart does not use a Bollinger band. Akash and Clore each
provide one rented/total ratio per observation, not a distribution from which
such a band could be estimated. The selected provider therefore gets an upper
rented-share line and area plus a lower capacity pane with rented and total
counts. Akash counts GPU units; Clore counts public on-demand servers. They are
never combined into one denominator, and the lower pane is labeled capacity,
not volume.

Discarded approaches:

- A browser-derived VM base-100 series was rejected because the publication
  metric belongs in gold and must be queryable outside the article.
- Raw H100 dollars, VM dollars, and sandbox cents on one axis were rejected
  because they describe different products.
- Capacity counts labeled as volume were rejected because no transaction
  volume is observed.
- A smoothed occupancy band was rejected because it would imply uncertainty
  or cross-sectional dispersion that the sources do not provide.

## Verification Commands

```sh
uv run sandbox-cost validate

uv run sandbox-cost check-public \
  --url https://d3n0n6h709c83f.cloudfront.net/sandbox-cost.json \
  --max-age-hours 2.5

uv run python -m unittest \
  tests.test_sandbox_cost \
  tests.test_vm_capacity \
  tests.test_adamsioud
```

## Verification Results

- Canonical evidence validation passed with 33 sandbox price observations, 38
  provider-batch summaries, 69 latest complete jobs, and 690 latest phase
  rows.
- The 31 focused sandbox, VM-capacity, and article tests passed, followed by
  all 85 repository unit tests.
- JavaScript syntax and both repository diff checks passed.
- Desktop browser inspection at 1280 pixels showed the absolute
  VM/VPS-versus-sandbox rate chart, cost-led workload sequence, relative
  H100/VM/sandbox chart, and occupancy/capacity chart without document-level
  horizontal overflow.
- The revised workload chart rendered 69 individual jobs, six published
  medians, and six published p25-p75 ranges in cost order: Novita, Daytona VM,
  Blaxel, E2B, Modal VM, and Modal gVisor. Runtime remained available in
  tooltips and the collapsed evidence table, not as a competing headline
  mode.
- Pointer-independent keyboard inspection exposed published cost, measured
  phase time, and the p25-p75 range through the chart live region. The relative
  price and occupancy source tabs also support keyboard switching.
- Responsive inspection at 390 by 844 pixels showed all six cost rows, the
  relative series, both occupancy panes, and no document-level horizontal
  overflow.
- Opening the VM disclosure kept the wide provenance table inside its own
  scroll wrapper.
- The refreshed public payload contains 23 complete seven-vendor VM
  observations. Its VM base-100 median and range fields carry query IDs
  `vm_capacity_fixed_cohort_rate_v3` and
  `vm_capacity_expanded_hourly_rate_v2`, confirming that DataFusion/gold,
  rather than browser code, owns the relative metric.
- The occupancy interaction showed eight retained Akash GPU-unit observations
  and three retained Clore public-server observations. The latest complete
  market run had a current Akash observation; retained Clore history remains
  selectable and is not mixed into the Akash denominator.
- The browser reported no console errors.
- The final public freshness check passed with no partial VM source runs or
  stale projection warning. The snapshot was 0.046 hours old and the newest
  complete VM observation was 0.066 hours old.

## Deployment Record

- The self-hosted Windmill worker was rebuilt as
  `compute-bazaar-windmill-worker:2026-07-25-article-cost-v6`, image digest
  `6c1fba1a322b2617a74d36da7f42f787a3577a3418a1987fb1cd5bce79303ffb`.
- The deployment recreated only `windmill_worker`; Windmill Postgres, server,
  Caddy, and their volumes were left running.
- The first production run using the new worker published gold run
  `gold-market-20260725T210300-82f47f78` and sandbox publication build
  `sandbox-cost-65f7252187d836d3` at `2026-07-25T21:04:11Z`.
- The resulting payload contains 23 complete seven-vendor VM observations, 69
  latest complete workload jobs, and the retained source/audit tables.
- AdamSioud commit `beb0a36` was deployed successfully by GitHub Pages and
  verified at
  `https://www.adamsioud.com/exemplars/compute/feeling_the_compute.html`.
- Compute Bazaar commit `786f74f` records the DataFusion query revisions,
  tests, documentation, and deployed article submodule pointer.

## Next Data Work

- Add a manifest-oriented inventory command that can summarize the live S3
  lake without relying on an ignored local cache.
- Extend daily schema checks to the discovery VM sources as their APIs settle.
- Keep the full seven-vendor hourly history running before deciding whether it
  earns its own public chart.
- Treat a controlled recurring same-workload benchmark as a new methodology,
  rather than extending the six historical harness generations into one line.
