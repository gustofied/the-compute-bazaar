# Sandbox And Common-Start Article Cards

Date: 28 July 2026

## Purpose

Promote two maintained sandbox-cost questions into the clean AdamSioud Compute
article without copying the older dashboard or moving calculations into the
browser:

1. What is the public hourly processor-and-memory rate for the audited
   four-processor, 8 GiB sandbox shape?
2. What measured phase time and estimated processor-and-memory cost did one
   pinned software workload produce across six sandbox variants?
3. How did coverage-qualified H100, exact-shape VM, and managed-sandbox
   advertised rates move after their first shared retained observation?

The first two questions share one card because they describe the price of the
sandbox allocation and the result of running the same software job on it. The
third is explicitly exploratory and remains a separate card.

## Data Decisions

The article reads:

```text
sandbox/rates.json
sandbox/workload.json
sandbox/relative.json
```

All use `compute_bazaar_card_v1`. The browser does not calculate medians,
percentiles, cost estimates, fixed membership, or rebasing.

The workload headline comes from the latest complete six-service DataFusion
run summary. It is not the median of six already-aggregated service medians.
The detailed chart retains all 69 complete aligned jobs from 72 source slots.
The audit table retains seven matching runs over five calendar days, including
repeated intraday runs. Because those runs span six harness methodology IDs,
they are not connected as one runtime trend.

The exploratory chart is built by the named DataFusion query
`gpu_vm_sandbox_common_start_v1`. It:

- accepts only broad-coverage H100 benchmark prints from the maintained
  advertised-price methodology;
- as-of joins each print to the latest complete seven-vendor VM observation;
- as-of joins the fixed eight-service sandbox rate;
- chooses the first real H100 print for which all three inputs exist;
- independently rebases each median and p25-p75 range to 100 at that point.

The chart can compare relative movement. It cannot compare delivered work,
executed transactions, demand, volume, utilization, or a complete invoice.
Raw GPU dollars, VM dollars, and sandbox dollars are retained in each gold row
and exposed in the tooltip rather than placed on one shared dollar axis.

## Visual Decisions

The card system uses four approved colors:

```text
Soft Linen  #EFEDE4
Soft Azure  #91AECB
Sage Green  #B7D07B
Warm Sand   #F3C888
```

The GPU card keeps the exact user-supplied ocean crop. Sandbox uses the
existing Babbage image from the AdamSioud repository. Relative movement uses
the existing Royal Exchange image. No generated illustration is used in these
two new cards.

The cover is a compact portrait object. Opening it expands downward to the
full analytical view in the same document position. Share replaces the detail
with a portrait publication card. API flips only that card and exposes one
HTTPS endpoint. The transition uses measured incoming and outgoing heights,
distance-aware duration, and a non-bouncy ease. Reduced-motion users receive
the same state changes immediately.

Dots remain information marks. The fixed-rate chart shows the four retained
source-rate events. The workload chart shows every complete job because each
dot is a measured observation. The dense GPU and common-start histories do not
gain decorative resting dots.

## Rolling Contract Compatibility

During deployment overlap, the frontend accepts the first workload-card
headline alias and derives the observation timestamp and 69-of-72 accounting
from the already published gold rows. The new worker publishes the canonical
headline fields directly. This compatibility exists only at the serialization
boundary; it does not recompute workload statistics.

## Initial Visual QA

Desktop at 1440 by 900 CSS pixels:

```text
GPU cover and detail                         passed
sandbox hourly-rate detail                  passed
same-job chart: 69 jobs                     passed
same-job ledger: six services               passed
source audit: seven runs                    passed
share front and API reverse                 passed
page-level horizontal overflow              0 px
```

Mobile at 390 by 844 CSS pixels:

```text
cover width                                 fits article
expanded GPU and sandbox cards              fit viewport
chart interaction surfaces                  fit viewport
audit table                                 local overflow only
page-level horizontal overflow              0 px
```

The common-start card remained `pending` against the pre-deployment public
worker, as expected. Final QA must be repeated after the worker publishes
`sandbox/relative.json`.

## Build And Verification

```text
cd external/AdamSioud
npm run build:compute
node --check exemplars/compute/compute-cards.js

cd ../..
uv run --with pytest pytest \
  tests/test_sandbox_cost.py \
  tests/test_vm_capacity.py \
  tests/test_adamsioud.py
```

## Next Refresh

The hourly Windmill market run rebuilds all three split contracts. The daily
StarSling source poll changes workload history only when upstream publishes a
new compatible, schema-valid run. Managed-sandbox marketing-page rates remain
manual reviewed evidence; adding a price observation requires checking its
billing unit, requested shape, effective/observed date, and archive link before
the next hourly build.
