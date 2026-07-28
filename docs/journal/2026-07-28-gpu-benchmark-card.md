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
portrait cover -> expanded chart -> share chart <-> API reverse
```

There is no modal, cloned chart, or stacked z-index presentation. Closing the
detail restores the cover in the same document position. Share replaces the
detail in flow. API flips the same chart card instead of opening another layer.

## Production Build

The article is still deployed as plain static HTML. A small checked-in build
boundary makes the component maintainable:

```text
gpu-index-card.tailwind.css -> compute-card.css
compute-cards.source.js     -> compute-cards.js
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

The initial object is a small portrait publication card with the blue-ocean
artwork supplied in the approved card sheet, a plain `GPU Price Index` title,
and the selected family at the foot. The committed WebP is an exact
`514 x 424` crop from the supplied screenshot at offset `+727+128`; it is not
the generated market-signal image used in the discarded pass.

The detail state uses the supplied palette as a restrained market instrument.
Its action rail sits outside the analytical surface:

```text
identity                                         API Share x
price, unit, observed time/change                    family tabs
selected GPU                                         time range
published benchmark line and published price range
```

Soft Linen (`#EFEDE4`) is the surface, Soft Azure (`#91AECB`) is the structural
color, and a deeper blue carries the line and selected controls. The share
front is a landscape chart artifact. Its reverse keeps the selected family,
current price, and exactly one HTTPS Gold endpoint. It does not expose
methodology clutter or a second price source.

Motion measures the outgoing and incoming panels and animates the article's
actual height with a distance-aware 780-1080 millisecond transition. The
incoming state reveals vertically while the outgoing state recedes, so the
card opens and closes in flow instead of flashing between fixed boxes. The
share/API reverse uses a measured 820 millisecond ease rather than a bouncy
spring. CSS owns layout and 3D face geometry. Reduced-motion users receive
immediate state changes.

## Data And Accessibility Decisions

- H100, H200, B200, and B300 use independent public documents.
- Ranges are 1D, 7D, and all retained history.
- `null` range values fall back to the benchmark value, never zero.
- The share and API views use the same selected Gold observation.
- The inactive share face is `aria-hidden` and `inert`.
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
chart populated during unfold                      passed
detail -> share front transition                   passed
share front -> API reverse                         passed
API endpoint                                       exact HTTPS Gold URL
console warnings/errors                            0
horizontal overflow                                0 px
```

Mobile at 390 by 844 CSS pixels:

```text
portrait cover fits article column                 passed
expanded controls wrap without clipping            passed
chart remains readable                             passed
share chart and API reverse fit viewport           passed
document scroll width equals viewport               passed
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
external/AdamSioud/exemplars/compute/compute-cards.js
tests/test_adamsioud.py
```

The former `compute-card.js`, `compute-card-motion.js`, and
`gpu-benchmark-card.js` implementations were removed.

## Share-First Control Rail Refinement

The second pass removed the blue internal toolbar from every promoted article
card. Open, API, Share, close, Copy endpoint, and Return to chart now sit in a
small external rail. This keeps controls in one predictable place without
making them part of the market object itself.

The original share face reused the cover artwork and editorial quote blocks.
That was discarded because it did not preserve the analytical object a reader
was trying to share. The maintained share front is now a 16:9 SVG artifact:

```text
identity and selected product
headline value and unit
selected published line/range view
observed time and selected window
```

The GPU artifact draws the selected benchmark and published middle range. The
sandbox rate artifact draws the reviewed fixed-cohort step series. The
same-job artifact draws the service-level p25, median, and p75 ranges. The
common-start artifact draws the three published DataFusion series and the
selected published range. None of these cards recalculate Gold values.

Share exports the exact SVG face as a 1600 by 900 PNG. Browsers with Web Share
Level 2 receive the PNG as a file; other browsers download it. API remains the
reverse face with one exact HTTPS endpoint. On that reverse, the control
label remains Share and returns to the share face; the UI never exposes an
implementation label such as "Front."

Browser QA covered:

```text
desktop cover -> detail -> share -> API            passed
external control rail                              passed
GPU line and range share artifact                  passed
sandbox rate and workload share artifacts          passed
mobile 390 by 844 layout                           passed
horizontal document overflow                      0 px
current v3 console warnings/errors                 0
```

The endpoint reverse gained explicit narrow-screen wrapping after mobile
inspection. The public bundle cache keys advanced to CSS `v=9` and JS `v=3`.

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

## Standalone Object And Transition Correction

The final card pass made the share object a real destination instead of a
temporary face inside the article. `Copy link` now produces a scoped
`present=card` URL that suppresses the prose shell and centers the original
live card. The URL retains only the selected card's relevant state. Share
exports the exact 16:9 SVG as a 1600 by 900 PNG and includes that permalink in
the native share payload.

The API reverse was rebuilt as an artwork-backed market object with reusable
key/value fields, one exact endpoint, and the current published value. The
field vocabulary can later hold RFQ or contract terms without treating the
current benchmark contract as an executable deal.

Browser tracing also isolated the late bottom-drop animation. The inherited
page applies `zoom: 0.8`; `getBoundingClientRect().height` therefore returned
80 percent of the layout-space height and that scaled value was written back
as CSS pixels. The transition now prepares the destination before measurement,
waits for its height to settle, and uses `offsetHeight` throughout.

Measured desktop opening after the fix:

```text
cover natural height                    334.4 px
intermediate measured heights           342.4, 356.7, 361.8, 366.4 px
detail natural height                   366.2 px
late post-animation drop                none
```

The reverse close followed the same continuous path back to 334.4 px.
Standalone desktop and 390 by 844 mobile views retained one centered card,
working Copy link, and zero page-level horizontal overflow.
