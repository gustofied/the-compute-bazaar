# Prime H100 Offer Reference And Ladder

## Question

Can the Prime Intellect availability catalogue support a useful H100
market-interface view without pretending that catalogue rows are orders,
inventory units, fills, or utilization?

## Source Audit

Prime's
[official availability documentation](https://docs.primeintellect.ai/api-reference/check-gpu-availability)
says that:

- `/api/v1/availability/gpus` is paginated;
- each item is a unique provider configuration;
- `cloudId` is the upstream identifier used for provisioning;
- `dataCenter` disambiguates the same cloud ID across locations;
- `gpuCount` is the requested machine shape;
- `prices.onDemand` is the GPU base price;
- separately adjustable disk, CPU, memory, or shared storage may add hourly
  cost;
- `stockStatus` and `isVariable` describe public catalogue state.

The live retained 27 July sample had three H100 configurations from two
upstream providers. Multi-GPU rows reported a total configuration price which
normalizes back to the same per-GPU base rate. Historical code had treated
`gpuCount` as an available-capacity lower bound. That was removed: it is not a
fleet count.

The
[`KTibow/does-pi-have-the-best-price`](https://github.com/KTibow/does-pi-have-the-best-price)
project was also inspected. It is a useful live source-comparison
implementation: it takes minimum current prices from Prime, Vast, and Lium
alongside several manually maintained rates. It does not retain historical
snapshots, calculate a provider-balanced reference, or model order lifecycle.
It therefore informed source coverage but was not copied as a benchmark
methodology.

## Adopted Method

The product is named an **offer reference** and **offer ladder**, not an order
book.

```text
Prime hourly bronze snapshot
  -> normalized Silver configurations
  -> cumulative Gold offer history
  -> observable lifecycle events
  -> one floor per upstream provider
  -> median reference + p25/p75 + low-price breadth
  -> centered $0.25 ladder
  -> public-safe JSON
  -> D3 article card and Curia queries
```

Eligible rows are secure, on-demand, available H100 80 GB configurations with
a positive USD price. The reference gives one constituent to each upstream
provider. `observed` requires at least three provider floors; a thinner
snapshot is labelled `indicative`.

The base GPU price remains the comparable headline. Minimum separately billed
resources are calculated and retained as a second field so a reader can see
that a deployable machine may cost slightly more. This avoids silently
rewriting the historical H100 series when resource defaults change.

Lifecycle classification is intentionally narrow:

- entered;
- remained;
- repriced higher or lower;
- stock label changed;
- left public availability.

The discarded language was fill, cancel, traded volume, liquidity, physical
inventory, or occupancy. The source does not provide the evidence necessary
for those claims.

## Frontend Decisions

The article receives one new narrative section rather than a detached trading
terminal. The card combines:

- the current provider-balanced H100 reference;
- a p25-p75 history band;
- low-price provider breadth;
- a centered current price ladder;
- meaningful lifecycle badges;
- one latest-change sentence;
- exact caveats and source links.

The card uses raw D3 and the shared `ComputeViz` pointer, tooltip, observation,
sharing, and standalone-card contracts. Empty centered ladder rungs are shown
with zero configurations; they provide spatial context and do not imply
orders. Dots are used only for the active inspected history observation.

## Maintained Outputs

Gold:

```text
fact_prime_h100_offer_history
fact_prime_h100_offer_events
fact_prime_h100_offer_reference_history
fact_prime_h100_offer_ladder
```

Curia:

```text
prime_h100_offer_reference:v1
prime_h100_offer_ladder:v1
```

Publication:

```text
dashboard/compute-bazaar/prime-h100-offer-reference.json
```

## Refresh

No new schedule is required. `PRIME_INTELLECT_API_KEY` already adds Prime to
the existing hourly Windmill provider scope. The same `market-hourly` run
ingests bronze and silver, rebuilds DataFusion Gold, writes the stable public
payload, and updates the article on its next fetch.

## Verification Record

The focused normalizer, two-snapshot lifecycle, DataFusion reference/ladder,
Curia, and public-safety tests pass. The complete repository suite passed:

```text
uv run python -m unittest
Ran 93 tests in 5.122s
OK
```

Both maintained browser scripts pass `node --check`, and both repositories
pass `git diff --check`.

The recurring worker was rebuilt as
`compute-bazaar-windmill-worker:2026-07-27-prime-h100-v1`. Only the Windmill
worker container was recreated; Windmill server, Postgres, Caddy, AutoMQ, and
all volumes remained running.

The production smoke observation
`market-prime-h100-smoke-20260727T134500Z` completed successfully with all 18
scheduled providers. Its Gold manifest is
`gold-market-prime-h100-smoke-20260727T134500Z`, using
`gold_gpu_market_v3`, and contains:

```text
fact_prime_h100_offer_history             142 rows
fact_prime_h100_offer_events              198 rows
fact_prime_h100_offer_reference_history    40 rows
fact_prime_h100_offer_ladder               11 rows
```

The public payload returned HTTP 200 through CloudFront with S3 versioning,
server-side encryption, and CORS access for `https://www.adamsioud.com`. The
live snapshot had three visible H100 configurations from one upstream
provider, so the current reference correctly published as `indicative` rather
than `observed`.

Browser QA covered the integrated article and standalone card at 1440 x 1000
and 390 x 844. The page had no horizontal document overflow. History range
controls, pointer tracking, keyboard arrow inspection, ladder
hover/focus details, source actions, and the standalone share view worked
without console warnings or errors. Tooltips stayed inside the viewport on
mobile. Production QA also caught and fixed a standalone-view delay for an
`indicative` current snapshot: the shared card loader now recognizes any
completed `data-viz-tone`, rather than waiting only for `live` or `warning`.
