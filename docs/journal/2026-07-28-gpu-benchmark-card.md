# GPU Benchmark Card Redesign

Date: 28 July 2026

## Purpose

The clean AdamSioud Compute article needed one real component before the rest
of the old dashboard could be reconsidered. The first component is the
observed GPU price benchmark because its data contract and methodology are
already maintained in The Compute Bazaar.

The browser reads four `compute_bazaar_card_v1` Gold documents:

```text
gpu-benchmark/h100.json
gpu-benchmark/h200.json
gpu-benchmark/b200.json
gpu-benchmark/b300.json
```

DataFusion and the Gold build calculate the benchmark. The browser selects a
family and retained window and renders the published values. No price is
embedded or recomputed in the article.

## Discarded Approach

The first pass kept a wide chart visible at all times and opened a cloned
portrait inside an overlay. It created competing depth states and separate
scripts for the chart, share card, and animation layer. It also loaded Motion
from a CDN.

That approach was retired. The article now has one in-flow object and one
state machine:

```text
portrait cover -> expanded chart -> share portrait <-> API reverse
```

There is no modal, cloned chart, or stacked z-index presentation. Closing the
detail restores the cover in the same document position. Share replaces the
detail in flow. API flips the same portrait instead of opening another layer.

## Production Build

The article is still deployed as plain static HTML. A small checked-in build
boundary makes the component maintainable:

```text
gpu-index-card.tailwind.css -> compute-card.css
gpu-index-card.source.js    -> gpu-index-card.js
```

Tailwind `4.3.3` compiles the semantic component stylesheet. D3 `7.9.0` and
Motion `12.42.2` are bundled by esbuild `0.28.1`. Production does not load a
Tailwind, D3, or Motion runtime CDN.

AdamSioud's old stylesheet is unlayered. Component rules are therefore emitted
unlayered after Tailwind's import so the component's specific selectors beat
the inherited editorial rules without `!important`.

Build from `external/AdamSioud`:

```bash
npm install
npm run build:compute
```

## Visual And Interaction Grammar

The initial object is a small portrait publication card with original market
signal artwork, a plain `GPU Price Index` title, and the selected family at
the foot. It follows the proportions of the supplied planning-card reference
without copying its brand or artwork.

The detail state is a compact black market instrument:

```text
identity                                         API Share Close
price, unit, observed time/change                    family tabs
selected GPU                                         time range
published benchmark line and published price range
```

The share front is a portrait editorial object. Its reverse keeps the artwork,
selected family, current price, and exactly one HTTPS Gold endpoint. It does
not expose methodology clutter or a second price source.

Motion drives the in-flow panel transition and portrait spring. CSS owns
layout and 3D face geometry. Reduced-motion users receive immediate state
changes.

## Data And Accessibility Decisions

- H100, H200, B200, and B300 use independent public documents.
- Ranges are 1D, 7D, and all retained history.
- `null` range values fall back to the benchmark value, never zero.
- The share and API views use the same selected Gold observation.
- The inactive portrait face is `aria-hidden` and `inert`.
- Controls remain native buttons with focus-visible treatment.
- The chart is keyboard inspectable with Left, Right, Home, and End.
- One point appears only for the active pointer or keyboard observation.
- Tooltip positioning uses viewport coordinates and the SVG view box, which
  avoids the CSS-zoom offset previously seen in Safari.
- Localhost uses the same-origin FastAPI snapshot proxy; production reads the
  public CloudFront contract.
- Deep links retain `view`, `gpu`, and `range`.

## Source And Contract Check

The production H100 card returned `compute_bazaar_card_v1` on 28 July 2026.
The observed contract included:

```text
benchmark         $2.59 per GPU-hour
retained history  963 observations
methodology       advertised_provider_floor_median_v1
```

These values were inspected to verify the contract. They are not stored in the
frontend.

## Visual QA

The component was tested against the live S3-backed FastAPI proxy.

Desktop:

```text
cover -> detail transition                         passed
detail -> share front transition                   passed
share front -> API reverse spring                  passed
API endpoint                                       exact HTTPS Gold URL
console warnings/errors                            0
horizontal overflow                                0 px
```

Mobile at 390 by 844 CSS pixels:

```text
portrait cover fits article column                 passed
expanded controls wrap without clipping            passed
chart remains readable                             passed
share and API portrait fit viewport                passed
document scroll width                              390 px
```

## Files

```text
external/AdamSioud/package.json
external/AdamSioud/package-lock.json
external/AdamSioud/exemplars/compute/README.md
external/AdamSioud/exemplars/compute/assets/gpu-index-signal.webp
external/AdamSioud/exemplars/compute/feeling_the_compute.html
external/AdamSioud/exemplars/compute/gpu-index-card.tailwind.css
external/AdamSioud/exemplars/compute/gpu-index-card.source.js
external/AdamSioud/exemplars/compute/compute-card.css
external/AdamSioud/exemplars/compute/gpu-index-card.js
tests/test_adamsioud.py
```

The former `compute-card.js`, `compute-card-motion.js`, and
`gpu-benchmark-card.js` implementations were removed.

## Verification

```text
npm run build:compute
npm audit --omit=dev
uv run python -m unittest tests.test_adamsioud
uv run python -m unittest discover -s tests
```

## Next Card Work

This is the first maintained article primitive, not a reason to force every
market object into one chart grammar. Prime offer depth, capacity, sandbox
workload cost, and future deal cards can reuse its production build, state
discipline, type scale, and sharing behavior while keeping a visual form
appropriate to each measurement.
