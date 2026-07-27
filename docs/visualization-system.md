# Compute Bazaar Visualization System

## Purpose

The visualization system turns Compute Bazaar gold products into compact,
source-backed article objects. It keeps the editorial character of AdamSioud
while giving charts a consistent interaction and sharing contract.

This is a behavioral substrate, not a visual template. Shared code must not
force every figure into the same border, padding, status sentence, legend, or
plot composition. The GPU ticker, compact market pulse, sandbox evidence
figures, workload distribution, and occupancy view keep distinct editorial
forms because they answer different questions.

The system uses raw D3 and SVG. EvilCharts is a design reference for
composition, active marks, shared configuration, and loading states; it is not
a runtime dependency. The maintained implementation is:

```text
external/AdamSioud/exemplars/compute/compute-viz.css
external/AdamSioud/exemplars/compute/compute-viz.js
external/AdamSioud/exemplars/compute/compute-market-history.js
external/AdamSioud/exemplars/compute/prime-h100-market.js
external/AdamSioud/exemplars/compute/sandbox-cost.js
```

The browser renders publication-ready gold data. It must not become a second
calculation engine. DataFusion and the recurring pipeline remain responsible
for medians, percentiles, benchmark membership, and public-safe exports.

## The Card Contract

A card is the smallest complete visualization that can be understood and
shared on its own. "Card" describes its identity and URL contract; it does not
require a visible rectangle. Each card can expose six layers:

1. **Identity**: one plain-language title and, where useful, a short subtitle.
2. **State**: loading, live, warning, or unavailable.
3. **Controls**: only choices that change the analytical question, such as
   product, range, or provider.
4. **Plot**: the visual encoding and direct interaction surface.
5. **Observation**: the selected date, measure, value, context, and source.
6. **Provenance and actions**: methodology and a stable share link.

Cards use a stable DOM id and `data-viz-card`. A title and initial state can be
declared in markup:

```html
<figure
  class="sandbox-figure viz-card"
  id="example-card"
  data-viz-card
  data-viz-title="Example observed price"
  data-viz-status-label="Loading source-backed data"
>
  ...
</figure>
```

`ComputeViz.enhanceCards()` adds the observation area, status footer,
methodology action, expanded-view action, share action, and accessible status
message. Compact figures can visually suppress repeated status copy while
retaining it for assistive technology.

The stable live-card URL is:

```text
?view=card&card=example-card#example-card
```

It opens the original card full-width with its current public payload,
provenance, article link, copy-link action, and copy-embed action. This is a
presentation mode of the article, not a second renderer or a copied dataset.
It does not serialize a temporary hover state or claim that the underlying
data will never change.

The iframe-safe URL is:

```text
?view=embed&card=example-card
```

Embed mode removes the article chrome and surrounding card header so the host
page controls spacing and framing. The generated iframe is lazy-loaded and
uses the same source-backed chart implementation. Its suggested height follows
the card type, and the embed retains an expand action back to the full live
card.

Standalone composition has three deliberate proportions:

- `headline`: the four-product GPU ticker and its opened history;
- `compact`: one market measure or the narrow provider-coverage view;
- `evidence`: workload, price-source, relative-movement, and occupancy plates.

Compact cards do not stretch to the evidence width. Evidence plates keep the
space needed for exact marks, controls, and labels. The full-card header owns
the title, so evidence figures suppress their repeated internal title in that
mode only. Embeds retain the internal title because they have no page header.
This is a presentation distinction, not a separate chart implementation.

These are live, view-only artifacts. They intentionally differ from a frozen
chart snapshot: refreshing a live card can show a newer hourly observation.
The static GitHub Pages article cannot emit unique server-rendered Open Graph
metadata for every query-string card. Rich social preview images therefore
require a separate deterministic snapshot/export step and must not be implied
by the live sharing control.

## Information Marks

### Lines

A line must state what continuity means.

- Use a step line for public price cards when a value is carried forward from
  one dated observation until the next.
- Use a direct linear line for exact observations when interpolation is only a
  visual guide.
- Use a smooth monotone curve only for a trend display where the source is
  sufficiently dense. It must not imply unobserved extrema.
- Never connect incompatible methodology generations as if they were one
  continuous series.

### Dots

Dots are information objects, not decoration.

- An active dot means the current pointer or keyboard selection.
- A resting dot is used only for a named event, source change, methodology
  boundary, or defensible inflection that has additional information attached.
- Dense market histories, including GPU price history, do not show a dot for
  every retained row.
- Sparse evidence charts may retain source-event dots when the dots communicate
  when a public rate was observed or changed.
- Exact observations remain reachable through the interaction layer even when
  no resting dots are drawn.

Selecting a dot publishes an observation object:

```js
ComputeViz.observe(chartNode, {
  date: "26 Jul 2026 at 10:00 UTC",
  title: "H100 observed benchmark",
  value: "$2.41 / GPU-hr",
  detail: "14 offers, 4 providers",
  color: "#52685d",
  sourceUrl: "https://example.com/source",
  sourceLabel: "Open source",
  actionUrl: "https://example.com/detail",
  actionLabel: "Open detail",
});
```

The source action points to evidence. The optional detail action is reserved
for a real product workflow such as a listing, dataroom object, or RFQ. A
decorative dot must never pretend to offer an action that does not exist.

### Bands

A band must encode an explicit range in the gold data.

- Middle-50-percent bands represent p25 to p75.
- Full-cohort envelopes represent the actual minimum to maximum.
- Availability bands require real numerator and denominator observations.
- A band is never added merely to make a chart look more financial.
- A sparse series must not be presented with a synthetic confidence interval.

Legends and captions name the range. Tooltips expose its numerical bounds.

### Offer Ladders

An offer ladder is allowed only when Gold supplies explicit price levels and
membership. It is not a visual license to invent an order book.

- The center marker is a named reference calculated in Gold.
- Every occupied level represents source-observed offers rounded by a declared
  increment.
- Empty centered rungs may be shown to make distance from the reference
  legible, but their count remains zero.
- Bar length may encode visible configuration count or provider count only
  when the label names that unit.
- Entered, repriced, remained, and left-availability marks are based on
  consecutive retained snapshots.
- Do not use bid, ask, fill, cancel, remaining volume, liquidity, or execution
  language unless the source exposes those objects.

The Prime H100 ladder uses $0.25 rungs, configuration breadth, distinct
upstream-provider breadth, and a provider-balanced reference. Its hover and
focus detail can link to Prime's matching catalogue, but it cannot claim an
individual public URL for every configuration when none exists.

## Semantic Series Configuration

Each rendered series should identify its evidence status:

| Status | Meaning | Presentation |
| --- | --- | --- |
| observed | Direct retained source observation | solid mark |
| derived | Deterministic gold calculation from observed rows | emphasized aggregate |
| estimated | Formula uses observed input plus an explicit assumption | labelled estimate |
| unavailable | Required source value is absent | no invented mark |
| outside cohort | Valid observation excluded from a fixed benchmark | quieter or dashed mark |

Color distinguishes series identity. Stroke, dash, label, and caption carry
evidence status so meaning never depends on color alone.

## Interaction Contract

All time-series charts use the shared `ComputeViz.localPointer()` and
`ComputeViz.positionTooltip()` helpers. This keeps pointer geometry consistent
under the article's CSS zoom and across Safari and Chromium.

The interaction surface:

- supports pointer movement;
- is focusable;
- uses left and right arrows to move between observations;
- supports Home and End;
- exposes an `aria-valuetext` summary;
- writes the current point into an `aria-live` region;
- leaves the selected observation visible below the plot after hover ends.

The floating tooltip helps scan. The persistent observation row enables
inspection, copying, opening evidence, and later product actions.

## Responsive Contract

- Cards and plots must fit a 390-pixel viewport without page-level horizontal
  overflow.
- Titles and controls wrap before type is reduced.
- Action buttons remain at least 24 pixels in the compact editorial layout.
- Dense tables may use their existing local overflow container; charts may not
  force the page wider.
- Card state and provenance remain visible on mobile.
- Motion is disabled when `prefers-reduced-motion` is active.

## Publication States

The status footer is deliberately short:

```js
ComputeViz.setStatus(card, {
  label: "Source-backed data loaded",
  tone: "live",
});
```

Supported tones are:

- `default`: source-backed visualization, still loading or static;
- `live`: the expected public payload loaded;
- `warning`: the payload failed or the card is intentionally incomplete.

Status text is operational truth, not marketing copy. It should be specific to
the figure, such as "Hourly seven-vendor cohort" or "Dated public rate-card
evidence," rather than a generic success message. Freshness timestamps remain
in the chart or article copy when they are part of the data.

## Adding a Chart

1. Define the analytical question and gold fields.
2. Add a stable card id and `data-viz-card`.
3. Reuse existing axis, band, line, tooltip, and interaction helpers.
4. State continuity, range, units, observation date, and source precision.
5. Return source or detail URLs in the tooltip observation where available.
6. Add pointer and keyboard coverage.
7. Test desktop and 390-pixel mobile layout.
8. Check loading, fallback, and unavailable states.
9. Verify that formulas still live in the pipeline, not in the page.

## Reference

- EvilCharts introduction: <https://evilcharts.com/docs>
- EvilCharts line composition: <https://evilcharts.com/docs/line-chart/static>
- EvilCharts tooltip pattern: <https://evilcharts.com/docs/ui/tooltip>
- EvilCharts chart configuration: <https://evilcharts.com/docs/chart-config>
- EvilCharts dot conventions: <https://evilcharts.com/docs/echarts/ui/dots>

These references informed the composition model. Compute Bazaar owns its D3
implementation, editorial styling, data contracts, and accessibility behavior.
