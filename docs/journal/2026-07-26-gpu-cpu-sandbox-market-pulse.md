# GPU, CPU, and Sandbox Market Pulse

## Objective

Turn the article's separate GPU, VM, capacity, and workload products into one
source-honest opening view without inventing a composite compute index.

The final order is:

```text
GPU
  H100 observed provider-floor benchmark
  Akash available GPU units / total GPU units

CPU
  exact 4-vCPU / 8-GiB seven-vendor VM median
  Akash available CPU millicores / total CPU millicores

Sandbox
  StarSling complete-run median estimated processor-and-memory cost
  StarSling complete-run median measured phase runtime
```

Price, available capacity, estimated cost, and runtime remain separate
measures and separate axes.

## Source Audit

The overview reuses maintained sources rather than adding a frontend data
path:

- H100 price comes from the coverage-qualified
  `advertised_provider_floor_median_v1` gold benchmark history.
- VM price comes from the fixed `public_vm_4vcpu_8gib_v2` cohort: Akamai
  Linode, Vultr, Scaleway, Azure, AWS, OVHcloud, and Oracle Cloud.
- GPU and CPU available share come from the Akash provider inventory API.
  The denominator is the matching total reported across online Akash
  providers. GPU uses GPU units; CPU uses millicpu.
- Sandbox evidence comes from the public StarSling HPC Sandbox Benchmark.
  Compute Bazaar polls its committed dataset and launches no paid workloads.

The StarSling source currently has seven matching four-processor runs over
five calendar days. It has two distinct runs on 22 July. The first four
matching runs contain five service rows. The final three contain the complete
fixed six-service cohort. All seven remain retained.

## Gold Contract

The new DataFusion query groups `sandbox_benchmark_batches` by source run and
publishes:

```text
gold/sandbox_workload_run_history.parquet
```

For every run it retains:

- source run ID, generated time, observed date, and original URL;
- source commit, workload signature, method ID, and machine shape;
- distinct service count and `fixed_cohort_complete`;
- median, average, p25, p75, minimum, and maximum measured runtime;
- the same statistics for estimated processor-and-memory cost.

The estimate is unchanged:

```text
estimated_processor_and_memory_cost =
  measured_phase_seconds / 3600
  * matching_public_hourly_processor_and_memory_rate
```

The query is allowlisted as `workload-run-history`, hashed into the build
identity, written to the immutable gold generation, included in manifest row
counts, and projected under `workload.run_history` in
`sandbox_cost_gold_v5`.

## Frontend Decision

The new market pulse sits before the detailed evidence sections in the main
AdamSioud Compute article. It is an overview, not a second article or a
replacement for the audit tables.

Controls:

```text
1D (default)
7D
1M
All
```

GPU, VM, and Akash rows accumulate with the hourly market heartbeat. StarSling
changes only when the daily public poll finds a compatible upstream run. If a
selected live window contains no StarSling run, the latest complete source
point stays visible with its real timestamp and an explicit note that it lies
outside the selected window. The renderer does not carry the value forward.

The browser only filters time windows and draws precomputed values. It does
not calculate benchmark values, medians, percentiles, available shares, or job
cost.

## Discarded Approaches

- One combined axis was rejected because GPU dollars, VM dollars, job cents,
  available share, and seconds are not commensurate.
- A single “compute utilization” series was rejected. Available capacity is
  not a running lease, processor activity, or useful work.
- Incomplete five-service StarSling runs were not mixed into the fixed
  six-service headline.
- StarSling values were not repeated hourly. An unchanged upstream source
  creates no new runtime observation.
- A broad worker-source `rsync` was stopped after it began including an
  irrelevant local Terraform provider binary. The release used a minimal
  build context containing only `.dockerignore`, package metadata, `src/`,
  and the worker Dockerfile.

## Production Release

Only the Windmill worker container was recreated. Postgres, Windmill server,
AutoMQ, and their volumes remained running.

```text
worker image
  compute-bazaar-windmill-worker:2026-07-26-market-pulse-v1

image digest
  sha256:3134a3b811ee34ff598cbb139fb6f2a335e61db32532e464a94c3a9a4213f0b2

market run
  market-pulse-release-20260725T2350

gold run
  gold-market-pulse-release-20260725T2350

sandbox build
  sandbox-cost-5bfb725c7fcd6350
```

All 18 provider inputs, Kafka, GPU gold, both VM source groups, sandbox gold,
dashboard export, and public publication returned `ok`. The market run status
was `success`.

Published history at release:

```text
eligible H100 prints                 57
complete seven-vendor VM points      28
Akash aggregate GPU points           13
Akash aggregate CPU points            3
StarSling source runs                 7
complete six-service StarSling runs   3
```

The data-quality status remained `warning` only because retained provider
normalization aliases and the B200/B300 observation targets are not all
complete. No provider or publication stage failed.

## Verification

Commands:

```sh
uv run --with pytest pytest tests/test_sandbox_cost.py -q
uv run --with pytest pytest \
  tests/test_windmill_bootstrap.py \
  tests/test_gpu_market_core.py -q
uv run --with pytest pytest \
  tests/test_sandbox_cost.py \
  tests/test_adamsioud.py -q
uv run ruff check \
  src/the_compute_bazaar/sandbox_cost/pipeline.py \
  tests/test_sandbox_cost.py \
  tests/test_adamsioud.py
node --check external/AdamSioud/exemplars/compute/sandbox-cost.js
uv run sandbox-cost check-public \
  --url https://d3n0n6h709c83f.cloudfront.net/sandbox-cost.json \
  --max-age-hours 2.5
```

Results:

```text
sandbox pipeline tests              21 passed
worker/provider focused tests       50 passed
article + sandbox focused tests     23 passed
ruff                                passed
JavaScript syntax                   passed
public freshness                    ok
partial VM source runs              none
```

Browser QA:

- desktop: 1280 by 720, six values rendered, no page overflow;
- mobile iframe viewport: 390 by 844, one-column pulse, 390-pixel document
  width, no horizontal overflow;
- 7D control selected all three complete StarSling runs;
- keyboard inspection exposed exact H100 value, provider count, p25-p75, and
  timestamp;
- desktop and mobile browser logs were empty.

## Next Refresh

The hourly Windmill schedule remains:

```text
f/compute-bazaar/market_hourly_hourly
0 0 * * * * UTC
enabled
```

The source-only StarSling poll remains daily. A new upstream run must pass the
pinned shape, workload signature, source rewrite, and schema checks before the
next hourly build can publish it. Check `workload-run-history` after promotion
and confirm whether the run is a complete six-service cohort before expecting
the public headline to advance.

## Sandbox Vendor Histories

The aggregate VM-versus-sandbox chart remains the first price comparison, but
the sandbox median now has a visible constituent view immediately below it.
The new chart renders all 33 retained public rate observations across 11
services:

- solid paths are the eight fixed-cohort services used by the median;
- dashed paths are Beam, Freestyle, and Sailboxes, retained outside that
  fixed-membership calculation;
- dots mark a series start or a changed public rate;
- step segments carry the last observed public rate to the next source date;
- the gold fixed-eight median and middle 50 percent remain the dominant marks.

This avoids two discarded presentations. A median-only chart hid the vendor
evidence, while treating every connected segment as an hourly market print
would overstate the source precision. The current view keeps both the aggregate
and its public rate-card evidence without changing any gold formula.

Focused verification:

```sh
node --check external/AdamSioud/exemplars/compute/sandbox-cost.js
uv run python -m unittest tests.test_adamsioud -v
git diff --check
git -C external/AdamSioud diff --check
```

Results:

```text
JavaScript syntax                 passed
article tests                     2 passed
desktop browser                   11 paths, 33 vendor dots, no console errors
mobile browser                    390 by 844, no horizontal overflow
keyboard inspection              vendor highlight and median tooltip passed
```

## Visualization Card System

The article had three interaction dialects: the GPU headline and history, six
compact market-pulse charts, and the larger sandbox/occupancy figures. They
shared an editorial visual language but duplicated pointer geometry, tooltip
placement, loading state, and provenance behavior.

The retained approach is a small native D3/SVG framework:

```text
compute-viz.css
compute-viz.js
```

EvilCharts was reviewed as a composition reference, especially its separation
of chart container, series, dots, tooltip, and configuration. Adding its React
and ECharts stack would not fit this static article, so no dependency was
added. The useful discipline was translated into the existing D3 code.

Decisions:

- the card, not the SVG, is the smallest shareable publication object;
- all 13 article visualizations have stable ids and one card contract;
- a floating tooltip remains useful for scanning;
- a persistent observation row keeps the selected point, value, context, and
  source actions available after hover;
- dots mean retained observations, while the active dot means selection;
- source and methodology actions are explicit;
- share links target the canonical article and stable card id;
- GPU history and sandbox charts use one CSS-zoom-aware pointer calculation;
- pointer and keyboard selection publish the same observation object;
- formulas remain in DataFusion/gold and are not moved into frontend code.

The discarded alternative was a generic dashboard component library. It would
have added a second visual language and a client framework without improving
the evidence model. The shared layer is intentionally small enough that the
article remains plain HTML, CSS, D3, and generated JSON.

The complete contract is documented in
`docs/visualization-system.md`, including line continuity, resting and active
dots, bands, evidence status, card states, share URLs, keyboard behavior,
mobile behavior, and the future `actionUrl` slot for listing, dataroom, or RFQ
objects.

Verification:

```sh
node --check external/AdamSioud/exemplars/compute/compute-viz.js
node --check external/AdamSioud/exemplars/compute/compute-market.js
node --check external/AdamSioud/exemplars/compute/compute-market-history.js
node --check external/AdamSioud/exemplars/compute/sandbox-cost.js
uv run python -m unittest \
  tests.test_sandbox_cost \
  tests.test_vm_capacity \
  tests.test_adamsioud -v
```

Results:

```text
JavaScript syntax                 passed
focused data and article tests   34 passed
desktop cards                    13 enhanced, 13 live
desktop overflow                 none
mobile viewport                  390 by 844, no page or card overflow
browser console                  no warnings or errors
keyboard state                   min, max, current, and value text exposed
source action                    archived E2B price observation opened
stable card link                 query and fragment highlight verified
```

Reader review removed the resting dots from dense GPU history. They repeated
the hourly sampling pattern without identifying a distinct event. GPU history
now keeps only the active pointer or keyboard marker. The framework rule was
adjusted accordingly: a resting dot must identify a source event, methodology
boundary, or meaningful inflection with additional information attached.
Sparse sandbox-provider dots remain only for a series start or changed public
rate. Unchanged observations stay in the interaction and source record without
receiving another visual mark.

The next visual review also pulled the shared system back from a generic
dashboard-card treatment. The stable id, share action, source action,
observation state, and keyboard behavior remain shared. Borders, shadows,
padding, legends, captions, and plot composition do not. The GPU headline
returns to its original horizontal-rule treatment, compact pulse figures sit
open in their editorial rows, and larger figures keep their own layouts.
Generic "Source-backed data loaded" copy was replaced by figure-specific
provenance such as hourly benchmark history, the seven-vendor VM cohort, dated
rate-card evidence, and the latest compatible StarSling cohort.

## Live Card Permalinks And Embeds

The stable card identity is now also a presentation mode. Each of the 13
existing cards receives an expanded-view action and its share control copies a
live, view-only card URL:

```text
?view=card&card=gpu-price-card#gpu-price-card
```

The page waits for the selected card's public payload, moves that original DOM
card into a full-width stage, and then asks the existing D3 renderer to lay
itself out again. No chart formula, dataset, or renderer is duplicated.
Expanded mode adds the article link, copy-link action, and copy-embed action.
The iframe URL uses the same implementation without article chrome:

```text
?view=embed&card=gpu-price-card
```

This follows the useful part of TradingView's sharing model: a view-only link
keeps the artifact interactive, while an iframe is the portable live object.
It deliberately does not pretend to be a frozen snapshot. A future
deterministic image exporter can capture a run id and observation timestamp
for social previews, but that is a separate artifact with different freshness
semantics. Static GitHub Pages also cannot serve card-specific Open Graph
metadata from query parameters, so no rich-preview promise was added.

Implementation decisions:

- reuse the exact article card rather than maintain one page per chart;
- derive URLs from the canonical article URL so local preview links never leak
  into copied publication links;
- reveal compact-card provenance in standalone and embed modes;
- keep embed mode frameless and let the host page own its outer composition;
- open GPU history automatically when that card is shared;
- dispatch one shared layout event after a card moves so D3 and SVG figures
  redraw at their expanded width;
- preserve responsive behavior and keyboard/pointer inspection.

Verification:

```sh
node --check external/AdamSioud/exemplars/compute/compute-viz.js
node --check external/AdamSioud/exemplars/compute/compute-market.js
node --check external/AdamSioud/exemplars/compute/compute-market-history.js
node --check external/AdamSioud/exemplars/compute/sandbox-cost.js
uv run python -m unittest \
  tests.test_sandbox_cost \
  tests.test_vm_capacity \
  tests.test_adamsioud -v
uv run ruff check tests/test_adamsioud.py
```

Results:

```text
JavaScript syntax                  passed
focused data and article tests    34 passed
ruff                              passed
normal article cards              13 enhanced, 13 expanded links
expanded desktop card             one card, 1120 px, no overflow
expanded mobile card              390 px viewport, no overflow
iframe mode                       one card, no page header, no overflow
browser console                   no warnings or errors
```

Visual checks covered the expanded GPU card, the dense eleven-vendor sandbox
rate history, the compact H100 pulse, and iframe mode. The old site-wide
`main` maximum width initially kept the standalone view at 900 pixels; the
card-specific shell now overrides that cap without changing the article
layout.

Publication:

```text
AdamSioud commit     def47eb
Pages workflow       30196099058
Pages result         success
Compute Bazaar pin   385b3f5
```

The public article returned 13 live cards, 13 expanded-view links, no warning
cards, no horizontal overflow, and no browser console warnings or errors. The
published H100 pulse also rendered successfully in both standalone and iframe
modes.

## Standalone Card Refinement

A second visual review kept the article treatment intact and tightened only
the live-card presentation. The original implementation made every expanded
card 1120 pixels wide, repeated evidence-chart titles and provenance, retained
the article's selected-card stripe, and hid the expand action inside embeds.
Those behaviors made the feature work but did not make every card feel native
to its content.

The retained system now uses three proportions:

```text
headline  1040 px maximum  GPU ticker plus opened history
compact    860 px maximum  single market pulse and coverage
evidence  1120 px maximum  source, workload, comparison, occupancy
```

Other decisions:

- a standalone header contains the single page title and sharing actions;
- evidence figures hide only their repeated internal title in full-card mode;
- provenance remains once at the bottom of the card;
- full-card pages hide redundant footer share and expand controls;
- embeds retain methodology, expand, and share controls;
- embeds no longer force a full-viewport body and use type-specific suggested
  heights;
- the selected-card stripe is removed in standalone and embed modes;
- normal article controls now honor the documented 24-pixel minimum target;
- mobile card pages use the available 366 pixels in a 390-pixel viewport
  without horizontal overflow.

Visual QA covered the H100 pulse, four-product GPU headline, eleven-vendor
rate history, StarSling workload distribution, and rental occupancy card on
desktop. The vendor, workload, pulse, and occupancy embed paths were also
checked at 390 by 844. All retained their original chart encodings and
controls; no generic container, shadow, or duplicate renderer was introduced.

Publication:

```text
AdamSioud commit     4a65703
Pages workflow       30197034540
Pages result         success
Compute Bazaar pin   de3985f
```

The deployed article returned all 13 cards in `live` state, 13 expanded-view
links, 24-by-24 rendered article controls, no horizontal overflow, and no
browser console warnings or errors. The public H100 compact card rendered at
its intended 860-pixel maximum with current hourly data.
