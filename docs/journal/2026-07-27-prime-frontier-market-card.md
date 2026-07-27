# Prime Frontier Offer Market And Card

## Goal

Generalize the first Prime H100 shelf into a maintained H100, H200, B200, and
B300 market view. Put each Prime configuration beside the wider Compute Bazaar
benchmark without presenting catalogue rows as physical capacity or executed
orders. Turn the article figure into the first reusable editorial
`market-card` primitive.

## Source Check

Primary Prime documentation reviewed:

- <https://docs.primeintellect.ai/api-reference/check-gpu-availability>
- <https://docs.primeintellect.ai/api-reference/availability/get-gpu-availability>
- <https://docs.primeintellect.ai/cli-reference/check-gpu-availability>
- <https://docs.primeintellect.ai/api-reference/provision-gpu>

The availability response supplies a list of unique configurations and a
pagination `totalCount`. Each row carries `provider`, `cloudId`, GPU type and
count, socket, location, stock label, price, and configurable resource
details. The distinct current `provider` values are therefore the defensible
source list. `totalCount` is a configuration count, not the number of free
GPUs.

Prime documents how a selected availability row can feed its provisioning
endpoint. This supports the phrase **requestable configuration**. The
availability API does not expose posted GPU quantity, filled quantity,
canceled quantity, remaining quantity, or a transaction price. It cannot
support an execution ladder or order book by itself.

## Design References

The existing AdamSioud GPU chart remains the primary visual language. Two
external references were used as component studies:

- Interface Craft: editorial restraint, fine rules, deliberate spacing, and
  tactile controls.
- <https://www.shadcnblocks.com/blocks/chart-card>: a chart card as a complete
  object with identity, current value, controls, plot, context, and actions.

No React, Tailwind, shadcn, or chart-card package was added. The useful
composition was translated into the existing HTML, CSS, D3, and `ComputeViz`
system.

## Data Decisions

The maintained families are:

```text
H100 -> H100_80GB
H200 -> H200_141GB
B200 -> B200_180GB
B300 -> B300_288GB (Prime raw request type B300_262GB)
```

For each family and retained Gold run:

1. Keep secure, available, positive-price, non-spot configurations.
2. Normalize the provider-reported base rate to USD per GPU-hour.
3. Keep one lowest eligible configuration per upstream provider.
4. Take the median of those provider floors as the Prime reference.
5. Keep p25, p75, best, provider count, configuration count, and providers
   within 10 percent of the Prime reference.
6. Join the matching Compute Bazaar provider-balanced benchmark for the wider
   market comparison.
7. Center the visual $0.25 shelf on the wider benchmark while marking both the
   wider benchmark and Prime reference.

The new Gold tables are:

```text
fact_prime_frontier_offer_history
fact_prime_frontier_offer_events
fact_prime_frontier_offer_reference_history
fact_prime_frontier_offer_ladder
```

The first generalized build migrates the cumulative H100 table and scans
canonical historical Gold manifests to recover prior H200, B200, and B300
Prime rows. Later builds read the generalized cumulative history directly.

The public file is:

```text
dashboard/compute-bazaar/prime-frontier-offer-market.json
```

`prime-h100-offer-reference.json` remains an H100 compatibility projection
from the same build.

## Visual Decisions

The card uses one selected product at a time rather than four compressed
small multiples. Product state is retained in `?gpu=H100|H200|B200|B300`, so
expanded, embed, and shared card URLs reopen the selected family.

The timeline contains:

- a solid wider Compute Bazaar benchmark;
- a stepped Prime provider-floor median;
- a Prime provider-floor p25-p75 band;
- low-price provider breadth bars;
- diamonds only for observable entry, exit, reprice, or stock-label changes;
- short exact-price ticks for configurations requestable in the current Prime
  catalogue.

The shelf contains:

- $0.25 display levels;
- separate market and Prime reference markers;
- bars measured in returned configurations;
- exact-offer ticks;
- `IN`, `MOVE`, `LEFT`, and `STAY` lifecycle labels.

`LEFT` replaces `OUT` because the latter can be mistaken for an execution.
Tooltips name the configuration and provider units and state that requestable
rows are not posted quantity.

## Discarded Approaches

- **Synthetic fills or remaining volume:** rejected because Prime does not
  expose those fields.
- **Using `gpuCount` as depth:** rejected because it describes machine shape.
- **Using API `totalCount` as fleet capacity:** rejected because it counts
  matching configurations.
- **Four copied cards:** rejected because it duplicates controls and makes
  comparison harder. One stateful card is more legible and shareable.
- **Raw GPU dollars and imagined execution volume on one plot:** rejected
  because the units and source evidence do not match.
- **Smooth interpolation:** rejected for this view. Hourly catalogue states
  are rendered as steps until the next observation.

## Verification Log

Static and unit verification:

```text
node --check external/AdamSioud/exemplars/compute/prime-frontier-market.js
node --check external/AdamSioud/exemplars/compute/compute-viz.js
uv run ruff check [changed Python files]
uv run python -m unittest discover -s tests

Ran 93 tests in 6.589s
OK
```

The Windmill worker image was rebuilt as
`compute-bazaar-windmill-worker:2026-07-27-prime-frontier-v1`. Only the worker
service was recreated. Windmill server, Postgres, Caddy, AutoMQ, and their
volumes stayed running.

The named smoke observation
`market-prime-frontier-smoke-20260727T145900Z` succeeded with all 18 scheduled
providers. Its Gold manifest is
`gold-market-prime-frontier-smoke-20260727T145900Z`, using
`gold_gpu_market_v4`, with:

```text
fact_prime_frontier_offer_history             271 rows
fact_prime_frontier_offer_events              346 rows
fact_prime_frontier_offer_reference_history   121 rows
fact_prime_frontier_offer_ladder                40 rows
```

The regular hourly run then completed successfully as
`market-20260727T150058-c40314f8`, proving that the deployed recurring schedule
uses the same build. It retained 1,825 listings and published
`prime-frontier-offer-market.json`.

CloudFront returned HTTP 200 with S3 versioning, AES256 server-side
encryption, and the expected `https://www.adamsioud.com` CORS origin. The
payload reports the missing execution fields explicitly and currently shows:

```text
H100  Prime $3.25  wider benchmark $2.59  3 configurations  Datacrunch
H200  Prime $4.50  wider benchmark $3.81  2 configurations  Nebius
B200  no Prime offer  wider benchmark $6.11
B300  Prime $7.50  wider benchmark $7.81  2 configurations  Datacrunch
```

The publication payload retains the full hourly benchmark history rather than
sampling it. It is approximately 3.2 MB as formatted JSON and 164 KB over the
wire with the deployed CloudFront gzip behavior.

Browser QA covered the integrated article and standalone card at 1,440 x
1,000, article width, and 390 x 844. H100, H200, B200, and B300 switching,
1D/7D/1M/ALL ranges, benchmark-only B200 handling, selected-product share
state, keyboard timeline inspection, shelf details, source links, and
tooltips all worked. The full history reaches 18 June. The mobile document
had no horizontal overflow, tooltip bounds stayed inside their panels, and
the console had no warnings or errors.

The laptop's mobile IP changed during the first synchronous smoke request.
Windmill still completed that job successfully; the client merely lost its
long-held HTTP response. Verification therefore used the durable Windmill job
record and S3 outputs, and the normal scheduled run completed immediately
afterward.

## Publication

The AdamSioud article commit is `0e286b9` and the matching Compute Bazaar
pipeline commit is `f71fb35`. GitHub Pages deployment `30279002252` completed
successfully. The production article at
<https://www.adamsioud.com/exemplars/compute/feeling_the_compute.html#prime-frontier-market-card>
loaded the new script and CloudFront payload without console errors; product
switching and selected-product standalone links also worked there.
