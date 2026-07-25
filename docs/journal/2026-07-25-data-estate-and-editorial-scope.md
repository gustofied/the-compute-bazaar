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
objects the same narrative weight as the two public questions:

1. What does the requested capacity cost before and after the sandbox layer?
2. How long did the same measured workload take, and what is its marginal
   processor-and-memory rate-card estimate?

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
- the current public feed passed the 2.5-hour freshness check at
  `2026-07-25T20:00:45Z`; its latest complete VM observation was
  `2026-07-25T19:28:05Z`;
- the ignored local `data/lake` cache did not contain the newest expanded VM
  build, while the public/S3-backed projection was fresh.

The last point is important: local ignored data is convenient for development,
but S3 manifests and gold tables are operational truth. Publication JSON is a
projection, not a database.

## Editorial Decision

Keep in the main article:

- one VM-versus-managed-sandbox rate history;
- the current headline rates and ratio;
- one latest same-workload distribution;
- compact runtime/cost and phase summaries;
- collapsed source and audit tables;
- the exploratory GPU/sandbox relative series and market-state section.

Demote from the main narrative:

- the separate flat, young seven-vendor VM-only chart;
- the historical provider-batch chart across six harness methodologies.

The VM offers remain available in one collapsed source inspection section. All
38 historical provider-batch rows remain in gold, the public payload, and the
collapsed audit table. No observation was deleted and no formula changed.

The runtime chart title changed from “Latest measured-phase distribution” to
“How long the same workload took.” The methodology copy still defines the
measured phase precisely; the heading now states the reader's question rather
than an internal data term.

## Data/Product Boundary

This pass adopts a durable rule:

```text
bronze/silver/gold may retain more than the article displays

article/dashboard/API selects views from gold

removing a chart never removes the source series

adding a chart never creates a browser-only metric
```

The seven-vendor hourly rate remains a useful future series. It should return
as a standalone public chart when enough elapsed history or actual price
movement makes it informative. Until then, it remains queryable data.

The historical workload summaries should be visualized again only when the
query groups comparable harness methodologies or a controlled recurring
benchmark supplies a genuinely consistent time series.

## Workload Comparison Redesign

The first simplified workload view still privileged runtime: it drew all 69
jobs and showed estimated cents only as a label. That made the rate-card
estimate look secondary even though the reader's question is explicitly about
both time and cost.

The revised primary view now:

- ranks six services by their published median;
- switches between measured phase time and estimated
  processor-and-memory cost without changing the constituent jobs;
- keeps both medians visible in a compact ranked ledger;
- retains every complete job for pointer and keyboard inspection;
- retains the published p25-p75 range as supporting dispersion;
- leaves all 38 cross-method historical summaries in a collapsed audit table,
  outside the primary visualization.

No benchmark formula moved into the browser. Version 5 already contains every
job, service medians, p25-p75 values, and cost estimates produced by the
maintained DataFusion/gold build. The D3 code now refuses a missing or
service-incomplete workload summary instead of deriving a replacement from
the raw jobs. Its permitted work is presentation: choosing a measure, sorting,
scaling, labeling, and interaction.

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
- The 31 focused sandbox, VM-capacity, and article tests passed.
- JavaScript syntax and both repository diff checks passed.
- Desktop browser inspection at 1280 pixels showed the simplified rate and
  workload sequence, the collapsed VM source disclosure, and no document-level
  horizontal overflow.
- The revised workload chart rendered 69 individual jobs, six published
  medians, and six published p25-p75 ranges. Switching to estimated cost
  reordered the services from the time ranking to Novita, Daytona VM, Blaxel,
  E2B, Modal VM, and Modal gVisor without changing the constituent count.
- Pointer-independent keyboard inspection exposed both measures and the
  p25-p75 range through the chart's live region. Arrow keys also switched the
  two metric controls.
- Responsive inspection at 390 by 844 pixels showed both full-width metric
  controls, all six chart rows, the two median columns, and zero document,
  article, or ranked-ledger horizontal overflow.
- Opening the VM disclosure kept the wide provenance table inside its own
  scroll wrapper.
- The browser reported no console errors.
- The public freshness check at `2026-07-25T20:27:25Z` passed with no partial
  VM source runs or stale projection warning; the newest complete VM
  observation was 0.457 hours old.

## Next Data Work

- Add a manifest-oriented inventory command that can summarize the live S3
  lake without relying on an ignored local cache.
- Extend daily schema checks to the discovery VM sources as their APIs settle.
- Keep the full seven-vendor hourly history running before deciding whether it
  earns its own public chart.
- Treat a controlled recurring same-workload benchmark as a new methodology,
  rather than extending the six historical harness generations into one line.
