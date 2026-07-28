# GPU Benchmark Card Redesign

Date: 28 July 2026

## Purpose

The clean AdamSioud Compute article needed one real component before the rest
of the old dashboard could be reconsidered. The first component is the
observed GPU price benchmark because its data contract and methodology are
already maintained in The Compute Bazaar.

The work deliberately did not move benchmark calculation into the article.
The component reads the existing `compute_bazaar_card_v1` family documents:

```text
gpu-benchmark/h100.json
gpu-benchmark/h200.json
gpu-benchmark/b200.json
gpu-benchmark/b300.json
```

DataFusion and the Gold build still calculate the benchmark. The browser only
selects a family and retained time window and renders the published result.

## Visual Grammar

The article remains plain HTML, CSS, and JavaScript. The card uses the
AdamSioud serif and mono typography inside a compact black market-instrument
frame rather than introducing Tailwind or a component framework. Motion is
loaded as a pinned ESM dependency for purposeful transitions. The structure is:

```text
identity                                      API  Share
price, unit, observed time/change              family tabs
selected GPU                                  time range
published benchmark line and price range
```

There are no decorative point markers. One point appears only while inspecting
an observation with a pointer or keyboard. The line is the published median of
one cheapest eligible advertised price per provider. The shaded area is the
published interquartile range of those provider floors.

The component keeps a small border radius, fine rules, no gradient, and no
generic dashboard furniture. The visible article card deliberately omits
provider counts, methodology links, constituent links, and explanatory copy.
Those contracts remain in the API and project documentation.

`Share` creates a separate portrait object rather than scaling or cloning the
wide article card. Its front contains the selected Gold trace, price, unit, and
observation. Its reverse contains an original technical scope composition,
selected family, published range, and price. The supplied Ordinal Defense
screenshots informed proportion and hierarchy only; their image, name, and
brand treatment were not copied into the publication.

Motion `12.42.2` drives the card entrance, data-state transition, portrait
reveal, and front/reverse spring. Reduced-motion users receive the same state
changes without animated travel. CSS owns all layout and 3D face geometry, so
the card stays legible if the animation module is unavailable.

## Data And Interaction Decisions

- The headline and history come from the compact public Gold projection.
- No prices are embedded in the HTML.
- `null` range values fall back to the benchmark value rather than being
  coerced to zero.
- H100, H200, B200, and B300 use independent public card documents.
- The ranges are 1D, 7D, and all retained history.
- `API` follows the selected family.
- `Share` preserves the selected family and range.
- The share front and reverse use the same selected Gold observation as the
  article card; they do not contain a second price source.
- The hidden share face is `aria-hidden` and `inert`, preventing keyboard focus
  from entering the reverse side before it is visible.
- The tooltip uses viewport-relative pointer coordinates and the SVG view box,
  avoiding the CSS-zoom offset that previously affected Safari.
- Keyboard inspection supports Left, Right, Home, and End.
- Localhost reads the existing same-origin FastAPI allowlisted snapshot proxy.
  The deployed article reads CloudFront directly.

## Production Contract Check

The production H100 card returned `compute_bazaar_card_v1` on 28 July 2026.
At the checked run it reported:

```text
as_of             2026-07-28T00:00:50.069536+00:00
benchmark         $2.59 per GPU-hour
provider floors   27
retained history  963 observations
methodology       advertised_provider_floor_median_v1
```

These values were inspected only to verify the contract. The frontend does not
store them.

## Visual QA

The card was rendered against the live S3-backed FastAPI proxy.

Desktop:

```text
live H100 value loaded
compact line and published range rendered
API and Share aligned in the card header
portrait front and reverse rendered
Motion spring reached the selected reverse state
console errors          0
```

Emulated mobile at 390 CSS pixels:

```text
document scroll width   390 px
card bounds             20.14 px to 369.86 px
card height             338.07 px
portrait bounds         85.32 px to 304.68 px
console errors          0
```

The interaction pass selected H200 and 7D, then verified:

```text
displayed value         $3.99
API family              h200
tooltip inside chart    yes
share dialog open       yes
share state             gpu=H200&range=7d
```

## Files

```text
external/AdamSioud/exemplars/compute/feeling_the_compute.html
external/AdamSioud/exemplars/compute/compute-card.css
external/AdamSioud/exemplars/compute/compute-card.js
external/AdamSioud/exemplars/compute/compute-card-motion.js
external/AdamSioud/exemplars/compute/gpu-benchmark-card.js
tests/test_adamsioud.py
```

## Verification

```text
node --check external/AdamSioud/exemplars/compute/compute-card.js
node --check external/AdamSioud/exemplars/compute/gpu-benchmark-card.js
node --input-type=module --check < external/AdamSioud/exemplars/compute/compute-card-motion.js
uv run python -m unittest tests/test_adamsioud.py
uv run python -m unittest discover -s tests
```

The full suite completed with 97 passing tests.

## Next Card Work

This is the approved base primitive, not a reason to force every market object
into one chart grammar. Prime offer depth, capacity, sandbox workload cost, and
future deal cards can reuse the frame, API/share behavior, type scale, and
interaction discipline while retaining visual forms appropriate to their
measurements.
