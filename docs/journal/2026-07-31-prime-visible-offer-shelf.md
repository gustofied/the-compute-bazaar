# Prime Visible Offer Shelf

## Question

Can the retained Prime Intellect catalogue show whether visible H100 and H200
offers are moving in and out of public availability, alongside a stable price
reference, without presenting catalogue changes as rentals or an order book?

## Adopted View

The article card uses the complete retained period for H100 and H200. It shows:

- the current provider-balanced market price;
- the market-price change since collection began;
- the current visible-offer count and its change since collection began;
- the market-price path aligned with the visible-offer count through time;
- the latest offer arrivals and departures on a separate Work view.

The market price is still calculated in Gold: select the cheapest eligible
offer from each upstream provider, then take the median of those provider
floors. This prevents providers with many regions or shapes from receiving more
weight merely because they publish more catalogue rows.

## Interpretation Boundary

The source exposes public availability, not completed rentals. The card
therefore says that a configuration entered or left public availability. It
does not say rented, filled, cancelled, utilized, or traded.

The first retained snapshot establishes the baseline and is not treated as a
new entry. A later disappearance may reflect a rental, provider withdrawal,
maintenance, a source change, or another catalogue transition. The retained
data cannot distinguish those causes.

## Data Contract

The recurring Gold export now writes:

```text
dashboard/compute-bazaar/prime-frontier-offer-shelf.json
```

The public contract contains only H100 and H200. It keeps current rows,
reference history, provider-level lifecycle events, stable `listing_id` and
`event_id` values, and public source URLs. It omits private lake locations and
credentials.

The larger `prime-frontier-offer-market.json` remains as a compatibility
fallback while the slim contract is deployed. The article does not calculate
the provider-balanced reference.

## Visual Decisions

The card follows the same four-state contract as the article's other market
objects:

- Cover: a compact card with the latest price, visible offers, and collection
  start date.
- Detail: an article-width chart with market price above and visible offers in
  an aligned lower strip.
- Work: a small signal chart plus the latest grouped offer arrivals and
  departures.
- Share: a 16:9 publication preview with both price and visible availability.

The detail chart intentionally does not put a dense event-glyph layer over the
price path. That version made the relationship harder to read. Every
provider-level event remains in the payload, while Work groups simultaneous
arrivals and departures into a short activity reel. Pointer and keyboard
inspection on Detail expose the observation time, market price, visible offers,
and seller count.

The four summary cells make the comparison explicit: market price, price change
since collection began, offers visible, and offer-count change since collection
began. This supports the exploratory question without labelling disappearing
offers as rented capacity.

## Refresh And Verification

The existing hourly market run remains the owner of ingestion and Gold export.
No frontend scraper or additional schedule was added.

Focused verification:

```text
npm run build:compute
uv run python -m unittest tests.test_adamsioud
uv run python -m unittest tests.test_dashboard tests.test_gpu_market_core
Ran 62 tests
OK
```

Browser QA covered Cover, Detail, Work, and Share at desktop width and the
390 px mobile breakpoint. The page has no horizontal overflow, H100/H200
switching updates the metrics and chart, the keyboard slider exposes the same
tooltip as pointer inspection, and a clean reload has no console warnings or
errors. The shared Work artwork needed one mobile grid reset; fixing it at the
shared component level also corrected the other article cards. The local
article proxy successfully falls back to the compatibility payload before the
slim object is deployed.

## Reproducibility And Release Audit

Canonical sandbox evidence validation reports 33 managed-sandbox price
observations across 11 services and 8 compatible StarSling source runs. Those
runs yield 44 provider-run means, 141 complete jobs, and 1,410 aligned phase
samples. The source manifest remains pinned to the reviewed upstream commit and
retains checksums and source URLs.

Two clean local builds from that evidence produced the same build ID,
`sandbox-cost-d7359443cfd4881b`, the same 50-file layout, and byte-identical
evidence and table artifacts. The four root-bearing lease and manifest wrappers
differ only because the test builds intentionally used different output-root
paths.

The full project suite reports:

```text
Ran 108 tests
OK
```

The public freshness workflow now checks the first-party
`https://bazaar.adamsioud.com/sandbox-cost.json` contract instead of the
underlying CloudFront distribution hostname. Historical journal URLs are kept
unchanged as contemporaneous evidence.

## Production Release

The AdamSioud article was published from commit `df8ed0d`. The Compute Bazaar
pipeline and pinned article revision were published from commit `7453ca5`.

The worker was built from a `git archive` of that exact pipeline commit, not
from the dirty local checkout:

```text
worker image: compute-bazaar-windmill-worker:2026-07-31-prime-shelf-v1
worker image ID: sha256:586eb0049b5790b4c76ceebd54686b5793f1cc978334fc23f158af379c38ba26
```

Only `windmill_worker` was recreated. Windmill Postgres, the server, Caddy,
AutoMQ, and their volumes remained running.

The named release observation completed successfully:

```text
market run: market-prime-shelf-release-20260731T1043Z
gold run: gold-market-prime-shelf-release-20260731T1043Z
dashboard export: dashboard-market-prime-shelf-release-20260731T1043Z
providers: 18
listings: 1,846
index values: 218
compute-market observations: 862
status: success
```

Every provider, Gold, sandbox-cost, VM-capacity, and dashboard-export check
reported `ok`. The Stage 1 operational check also reported `overall: ok`, one
healthy worker, and the enabled hourly schedule `0 0 * * * *`.

The public shelf contract is:

```text
https://bazaar.adamsioud.com/prime-frontier-offer-shelf.json
```

It is S3-versioned, encrypted at rest, served through CloudFront, contains no
private S3 references, and currently retains 143 H100 and 142 H200 hourly
observations. Production browser QA covered Detail, Work, Share, H100/H200
switching, semantic chart descriptions, and desktop overflow. It reported no
console errors. The same compiled CSS and JavaScript passed the earlier 390 px
mobile QA before publication.
