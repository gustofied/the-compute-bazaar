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
observations across 11 services and 10 compatible StarSling source runs. Those
runs yield 56 provider-run means, 281 complete jobs, and 2,810 aligned phase
samples. The source manifest is pinned to reviewed upstream commit
`530243df34f12dc8c2e49528b40b17c2dbd523b9` and retains checksums and source
URLs. The source audit admitted the new 30 and 31 July runs because both match
the fixed 4-vCPU, 8-GiB, 40-GB shape; the five earlier 2-vCPU runs remain
rejected.

### Prime share contract follow-up

Browser QA exposed one remaining contract mismatch: the Prime Work card could
turn into the Share panel, but Share copied only the live article query string.
The GPU card already copied an immutable publication URL with Open Graph and
Twitter preview metadata. Prime now uses the same crawler-preview/live-handoff
pattern. Every hourly build emits one H100 and one H200 publication page plus a
1200-by-630 price-and-visible-offer image. The extensionless publication URL
redirects a human reader to the standalone interactive card, while social
crawlers receive the frozen title, description, and image. The copied link is
read from the Gold-derived public contract; the browser does not construct a
publication identity.

Two clean local builds from that evidence produced the same build ID,
`sandbox-cost-8db5fb3b77815a0a`, the same 50-file layout, and byte-identical
evidence and table artifacts. The four root-bearing lease and manifest wrappers
differ only because the test builds intentionally used different output-root
paths. The two public payloads also differ only in their root-bearing
publication-manifest reference.

The full project suite reports:

```text
Ran 110 tests
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

## Publication And Shared-Surface Follow-up

The first standalone Prime Work screenshot exposed a frontend contract bug
rather than a data or publication failure. The shared Work and Share
components consume the GPU reference card's `--index-*` design tokens. The
Prime card defined only its own `--prime-*` palette, so several shared
background declarations became invalid and allowed the low-opacity Munch page
backdrop to show through the card.

The Prime component now maps its palette onto the shared reference-card token
contract and participates in the shared Work typography selectors. The
generated stylesheet cache key moved from `v=26` to `v=27`; the corresponding
article contract test was updated. AdamSioud commit `b1df916` contains the
source CSS, compiled CSS, and article cache key.

Desktop browser QA confirms that the standalone Work surface has an opaque
linen-and-paper body, a readable D3 signal, and the short observable-change
reel. Flipping to Share yields the clean 16:9 publication chart instead of a
translucent Work card. At a 390-by-844 viewport the card has no horizontal
overflow (`scrollWidth == clientWidth == 390`), all labels fit, and the loaded
chart and activity rows remain readable. The browser console reports no
warnings or errors.

The publication-enabled worker was built from exact Compute Bazaar commit
`9579f9a`:

```text
worker image: compute-bazaar-windmill-worker:2026-07-31-prime-publications-v2
worker image ID: sha256:fef500b8c4f7d492a27585f9a856e2421fc8d6c3c09a4a573d2a8b1ec24e08e7
```

Only `windmill_worker` was recreated. The database remained healthy and the
Windmill server, Caddy, and AutoMQ containers remained running.

The regular 12:00 UTC hourly observation completed after deployment:

```text
market run: market-20260731T120000-c6d7195b
gold run: gold-market-20260731T120000-c6d7195b
dashboard export: dashboard-market-20260731T120000-c6d7195b
providers: 18
listings: 1,816
price index values: 225
compute-market observations: 859
status: success
```

Every provider and the Gold, sandbox-cost, VM-capacity, discovery, and
dashboard-export checks report `ok`. The Stage 1 check reports `overall: ok`,
one healthy worker, and the enabled hourly schedule `0 0 * * * *`. A manual
shell inside the long-running worker container does not receive Windmill
resource variables, because Windmill injects those credentials into individual
jobs. The successful provider manifests record `publish_mode: kafka`; that is
the relevant publication proof for the scheduled path.

The public Prime shelf contains no `s3://` references. It points to the
relative public manifest path
`publications/prime-gpu-market/manifest.json`. The current manifest contains
two immutable rows, H100 and H200. Each extensionless publication page exposes
Open Graph and Twitter large-image metadata, hands a human reader to the
standalone live card, and uses a 1200-by-630 PNG preview.

Final verification:

```text
npm run build:compute
python -m unittest discover -s tests
Ran 110 tests
OK

uv run gpu-prices stage1-check \
  --windmill-base-url http://127.0.0.1:18081
overall: ok
```

## What The Retained Shelf Says

The card pair supports the market-microstructure thesis, but only in a
qualified form. The broad GPU Price Index is a multi-provider observed market
reference. The Prime card is a narrower view of one aggregator's visible
seller floors and offer churn. Their difference is useful information rather
than an error.

The cleaned publication run
`gold-market-prime-copy-release-20260731T1233Z` retains 147 H100 and 146 H200
hourly observations from 25 through 31 July 2026. H100 moved from $3.72 with
four visible offers to $2.82 with three, while the contemporaneous broader
Compute Bazaar H100 benchmark was $2.50. H200 remained at $4.50 while visible
offers moved from one to two; its broader benchmark was $3.62.

Simple visible-offer count is not a complete price model. Its Pearson
correlation with the Prime reference is only -0.108 for H100, but -0.643 for
H200. The hourly transition directions are more revealing:

- H100: an offer-count decline coincided with a price rise 27 times and a
  price decline 16 times. An offer-count increase coincided with a price
  decline 23 times and a price rise 11 times.
- H200: all 10 price-changing observations after an offer-count decline moved
  upward; all 10 price-changing observations after an offer-count increase
  moved downward. Most H200 hours remained flat.

This is consistent with visible scarcity and seller-floor composition shaping
an advertised marketplace reference. It does not establish causality or reveal
which disappearances were executed rentals. In particular, the H100 result
rejects the stronger claim that price follows total visible count mechanically.
Which providers, machine shapes, cluster sizes, regions, and price levels remain
on the shelf matters.

Visually, the cards expose the ingredients but the placeholder article prose
does not yet articulate the conclusion. Detail aligns price and visible offers;
Work exposes arrivals and departures at observed price levels; the main GPU
card supplies the broader reference. The eventual article needs one short
bridge between those objects: the benchmark describes the advertised market,
while the Prime shelf shows how visible supply composition can move around and
away from that reference.

## 2026-08-01: Price-level shelf view

The first revision exposed every current price level in a full-width ladder and
every retained configuration as a separate horizontal trace. It was accurate,
but it spent too much space on labels and made the main price path harder to
read. That version was discarded.

The final card follows the compact two-pane convention used by market charts:

- the upper pane keeps the Prime price dominant, with the broader Compute
  Bazaar market price as a quiet dashed comparison;
- the lower pane restores the hourly offer shape, now stacked into lower,
  middle, and upper asking-price bands;
- the three bands divide the retained asking-price range into equal thirds and
  count configurations in each band at every observation;
- the four headline values are simply Price, Change, Offers, and Providers;
- the Cover and Share SVG use the same price-plus-offers hierarchy.

This is deliberately an information reduction. Exact providers, machine
shapes, listing identities, and observed prices remain in the Gold contract
and Work view. The article chart answers the faster question: did the price
move, did the number of offers move, and did the offer mix shift toward lower
or higher asking-price bands?

The browser still calculates no benchmark. The Prime reference, broad market
reference, offer history, current offers, stable listing identities, and
machine shapes all come from the public Gold contract. The browser only groups
retained rows into three display bands and renders the supplied evidence.

Verification covered the article-width Detail state and a 390-pixel mobile
breakpoint. The mobile layout has no horizontal overflow, the D3 chart remains
readable, and hourly observations remain keyboard inspectable through the chart
slider. The chart title, description, and slider provide the bounded
screen-reader interface.

## 2026-08-01: Card hierarchy pass

Removed the observation-count/provider tagline beneath the Prime title. The
Detail masthead now states only the latest observation time; Price, Change,
Offers, and Providers sit in one shallow data ribbon with inset separators.

Share artifacts now use one hierarchy across GPU Index, Prime GPU Market,
Sandbox Cost, and Rate Movement: title and observation time in the masthead, a
rule, the selected measure and value, then the chart. Prime and GPU Index show
change as a separate right-aligned value instead of a sentence. Repetitive
footer counts were removed. Sandbox workload shares name the actual measure,
Estimated Job Cost or Measured Runtime, instead of repeating Sandbox Cost.

The first compact Prime metric passes still looked like a four-cell table, then
became too sparse when the dividers were removed. The final readout has two
intentional parts: one dominant price and unit on the left, and a grouped
telemetry rail for Change, Offers, and Providers on the right. A shared baseline
and two horizontal rules anchor the measurement without recreating table cells.
On narrow screens the telemetry rail moves below the price without horizontal
overflow.

The remaining filled segmented controls were visually heavier than the data.
GPU-family quote selectors now show a quiet instrument label over a tabular
price, with a two-pixel accent underline marking the active family. The same
underline interaction is used for chart ranges, sandbox views, cost/runtime,
and relative-rate controls. This removes the generic filled-pill treatment
while preserving keyboard tab and pressed states.

An optical-alignment pass then removed two inherited article styles from the
card interiors. The Prime summary no longer receives the site-wide `header`
inset, so its title, readout, and plot share one left edge. The GPU plot title
no longer receives the article-wide heading margin, removing the accidental
blank strip above the chart. Summary spacing is now consistent across the two
market cards.
