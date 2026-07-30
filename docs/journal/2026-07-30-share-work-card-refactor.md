# Share and Work Card Refactor

Date: 2026-07-30

## Purpose

The article had accumulated four overlapping ideas: an analytical chart, an
API panel, an image exporter, and a standalone card. This pass reduced those
ideas to one reusable market object with three meaningful faces:

```text
cover -> detail <-> share
              <-> work
```

The cover and detail opening behavior were retained. Share is the portable
chart face. Work is the source-backed reverse. The standalone route presents
those two faces without the article shell.

## Decisions

- Keep the existing D3 renderers and Motion transitions. No second chart
  library or frontend framework was added.
- Restore a draw transition when GPU family or range changes. The selected
  value and timestamp use a short Motion fade/translate. The previous D3 plot
  recedes while the next scale, grid, provider range, and four price paths
  enter; the paths then reveal in sequence.
- Remove the four-product quote strip from the GPU Share face. It now leads
  with only the selected GPU and price, while the other products remain quiet
  contextual lines.
- Remove the red final-point decoration. A point is shown only during chart
  inspection, not as ornamental punctuation in the Share artifact.
- Replace `Publication link` and `Share image` with one `Share` action. It
  copies the immutable GPU publication URL and reports
  `Copied. Ready to share.` Sandbox and relative cards copy their standalone
  URLs until frozen exporters exist for them.
- Give Work the exact same outer sleeve and aspect ratio as Share. Its retained
  content is one public JSON endpoint, one real sparkline, and three concise
  processing stages.
- Adapt Rerun's stewardship-feed rhythm rather than its exact styling: compact
  rows, restrained selected state, slow automatic advance, and pause on hover
  or keyboard focus.
- Keep Edvard Munch's *The Sun* as an environmental standalone background, but
  make it inert. Navigation now lives in one top-left article return. One
  attached control flips between Share and Work.
- Frozen GPU publication pages remain necessary for literal Open Graph and X
  metadata. Their preview links now open the matching standalone interactive
  card rather than the inline detail view.

## Discarded Approaches

- A separate native file-share and PNG-download control duplicated the frozen
  publication system and made the rail feel like a toolbar. It and its unused
  browser-side PNG conversion helper were removed.
- The earlier Work inspector repeated schema, methodology, coverage, and
  observation-window prose inside a small card. Those facts remain in public
  JSON and documentation; the card keeps only what helps a reader understand
  the active object.
- The old Work row container inherited a horizontal carousel. Browser QA showed
  clipped labels and three compressed columns. It was reset to a vertical reel
  so every stage remains legible.
- The standalone painted background was previously a page-sized article link.
  This made the card appear to sit on top of the article rather than exist as
  its own publication. It is now decorative only.

## Data and Methodology Boundary

No benchmark formulas, filters, source membership, units, or historical rows
changed in this UI pass.

The browser continues to read:

```text
gpu-benchmark/{h100,h200,b200,b300}.json
sandbox/rates.json
sandbox/workload.json
sandbox/relative.json
```

GPU medians and provider ranges, the fixed sandbox rate cohort, same-job cost
and runtime summaries, and common-start indexes are still computed in the
maintained Gold/DataFusion pipeline. Work sparklines are drawn from the same
retained series already published to the chart; they are not frontend-derived
benchmarks.

The publication schema moved from `compute_bazaar_publication_v4` to
`compute_bazaar_publication_v5` because the frozen image composition and live
handoff URL changed. The card-neutral route schema and extensionless public
path remain unchanged.

## Visual QA

Checked in the local article at desktop and 390-by-844 mobile sizes:

- GPU detail, Work, Share, and standalone Share-to-Work flip
- sandbox workload Share and Work
- relative-rate Share and Work
- no horizontal overflow at 390 px
- no browser console warnings or errors
- all Work rows visible after the vertical-flow correction
- standalone internal rails hidden
- one top-left article return and one attached flip control
- share copy confirmation visible after interaction

The frozen 1200-by-630 GPU social image was rendered separately and inspected.
It contains the selected GPU value, four contextual price paths, provider range,
observation time, range label, and no terminal red dot.

## Unified Share Link Contract

The first Share implementation exposed two incomplete paths:

- the immutable `bazaar.adamsioud.com/publications/...` object produced a rich
  social preview but landed on the frozen fallback page;
- the direct AdamSioud article query opened the polished standalone Share card
  but could not publish per-state Open Graph metadata from static HTML.

The publication wrapper now owns both jobs. It retains crawler-readable Open
Graph and X tags and a frozen 1200-by-630 PNG, then uses
`window.location.replace(...)` to hand a human browser to the exact
`view=share&present=card` article state. Social crawlers do not execute that
handoff. The canonical publication URL remains immutable and continues to
identify the observation, view, and content revision.

GPU, Sandbox Cost, and Relative Rate Movement now use the same contract. Their
public card payloads expose one publication object per selectable state, and
all three Share controls copy that immutable URL. A quiet line below the card
keeps the selected subject, range or measure, change, and observation time
visible. For example:

```text
B200 / 7 days / up 44.5% over 7 days / observed 30 Jul 2026, 14:05 UTC
```

The copy confirmation is temporary; the state description returns after it.
The frontend does not calculate publication values or revisions.

## Verification Commands

```bash
cd external/AdamSioud
npm run build:compute

cd ../..
uv run python -m unittest tests.test_publications
uv run python -m unittest discover -s tests
```

The focused publication suite passes five tests and the full repository suite
passes 106 tests. `pytest` is not part of the default UV environment, so the
repository's `unittest` suite was run directly.

## Refresh and Deployment

The production Windmill worker was rebuilt as:

```text
compute-bazaar-windmill-worker:2026-07-30-share-work-v5
sha256:835ebcc5023bce32013da1750a02932d2e6d6bca20db6bb5c6cabdbf4fc0631a
```

The first top-of-hour run on that image completed in 352 seconds:

```text
market_run_id: market-20260730T140000-3b0b6d65
gold_run_id: gold-market-20260730T140000-3b0b6d65
dashboard_export_id: dashboard-market-20260730T140000-3b0b6d65
status: warning
listing rows: 1,697
index-value rows: 226
publication schema: compute_bazaar_publication_v5
```

Seventeen provider inputs and every Gold, sandbox, VM-capacity, and dashboard
build check passed. `cloudgpuprices.com` exceeded its 60-second read timeout,
so the market run correctly retained `warning` rather than claiming complete
provider coverage.

An explicit one-off smoke was submitted at the same time as the scheduled run.
Windmill queued it behind the scheduled observation, and the waiting HTTP
request reached its ten-minute deadline after the second job had run for 285
seconds. Windmill cancelled that duplicate job; it did not write a complete
market-run manifest or replace the successful scheduled export. The successful
scheduled run is the deployment proof.

Production checks confirmed:

1. the four public GPU card payloads advertise publication schema v5;
2. all twelve family/range publication objects are present;
3. extensionless publication HTML and its `.png` social image return 200;
4. Open Graph and X metadata point to the immutable 1200-by-630 image;
5. `Open interactive card` targets the matching
   `view=share&present=card` article state.

The article implementation was published from AdamSioud commit `cfcfb30`.
GitHub Pages workflow `30550366981` completed successfully. The corresponding
Compute Bazaar pipeline and documentation commit is `5468e7f`.

Final production browser checks used the canonical article and fresh H200
publication:

```text
https://www.adamsioud.com/exemplars/compute/feeling_the_compute.html
https://bazaar.adamsioud.com/publications/gpu-index/h200/7-day/2026-07-30-1405-utc-3aad21c527
```

The deployment tunnel was closed afterward. The temporary TCP/8080 rule and
two obsolete mobile-IP rules were revoked; the current one-address SSH rule
was retained. The unused v4 worker image was removed without pruning active
containers or Docker volumes.

Old publication URLs remain immutable and valid. They are not rewritten.

## Unified Publication Rollout

The final publication implementation was deployed from:

```text
Compute Bazaar commit: 7f1b6f4
AdamSioud commit: 570499d
worker image: compute-bazaar-windmill-worker:2026-07-30-unified-publications-v6
worker image ID: sha256:46b67ca2120ca0aedf2d832a0a30c252d2b37b23ca2cabc2433392c9140dffb6
Windmill job: 019fb39f-4990-5099-5437-033176db05bd
market run: market-unified-publications-v6-20260730T1522
gold run: gold-market-unified-publications-v6-20260730T1522
dashboard export: dashboard-market-unified-publications-v6-20260730T1522
```

The job completed successfully with an overall `warning`: seventeen provider
inputs succeeded and one provider input failed. Gold tables, card contracts,
publication wrappers, and public images were still produced. The warning is
retained because a publication should not imply complete provider coverage
when one source was unavailable.

The deployed payload now includes publication contracts for:

- all four GPU families and each 1-day, 7-day, and retained-history view;
- the fixed-cohort sandbox hourly-rate view;
- both measured sandbox workload views, estimated cost and runtime;
- GPU, VM, and sandbox relative-rate views for 1 day, 7 days, and retained
  history.

Fresh production checks confirmed that every publication wrapper has
Open Graph and X metadata, a 1200-by-630 PNG, and an exact browser handoff to
the polished standalone card. The following representative objects were
checked end to end:

```text
https://bazaar.adamsioud.com/publications/gpu-index/b200/7-day/2026-07-30-1505-utc-e8769f9e26
https://bazaar.adamsioud.com/publications/sandbox-cost/rates/hourly-rate/2026-07-24-0000-utc-9f22c066fe
https://bazaar.adamsioud.com/publications/relative-prices/gpu/7-day/2026-07-30-1505-utc-9f22c066fe
```

All three opened their matching `view=share&present=card` state with no
horizontal overflow or console errors. Their quiet publication labels also
matched the Gold payload. The full repository suite now passes 107 tests, and
the changed Python files pass Ruff.

Publication URLs are content revisions rather than aliases. A URL created
before the live-handoff implementation continues to show its original frozen
page. It is deliberately not mutated into a different historical artifact.
The current card payload always points Share at the newest publication
contract for the selected state.
