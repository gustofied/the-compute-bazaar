# Four-Level GPU Index Card

Date: 29 July 2026

## Purpose

Restore the useful four-product context from the Compute Bazaar workhouse to
the canonical AdamSioud article card, without moving benchmark calculation
into the browser or turning the component into a generic dashboard.

The card continues to read four independent public Gold contracts:

```text
gpu-benchmark/h100.json
gpu-benchmark/h200.json
gpu-benchmark/b200.json
gpu-benchmark/b300.json
```

H100, H200, B200, and B300 remain separate benchmarks. The frontend does not
average or normalize them into one synthetic GPU value.

## Audit

The earlier canonical card presented only the selected product line. Its tabs
switched between four separate views, so the reader could not see the current
price levels together. The share artifact repeated that single-series view
and read more like a report slide than a portable market object.

The redesign keeps the existing stack and identity:

```text
plain HTML
Tailwind 4 source CSS
D3 7
Motion 12
Soft Linen and Soft Azure
Geist, Palatino, and JetBrains Mono
```

No framework migration, new runtime dependency, generated artwork, or data
contract change was introduced.

## Chart Decisions

The expanded chart now:

- shows all four product histories on one linear USD-per-GPU-hour axis;
- starts the y-axis at zero so the absolute price-level differences remain
  honest;
- keeps the selected product strongest and renders only its published
  lower-to-upper range band;
- turns each product tab into a compact latest-price quote;
- uses points only during active inspection, not as resting decoration;
- exposes all matching product prices in the tooltip and through keyboard
  inspection;
- omits a comparison value when its nearest observation is more than 90
  minutes away from the selected timestamp.

The selected product still owns the headline value, change calculation,
range band, API endpoint, URL state, exported file name, and focus order.

## Share Object

The share artifact remains a 1200 by 675 SVG so the existing 1600 by 900 PNG
export stays compatible. Its standalone presentation is a smaller windowed
object:

- four latest product values across the top;
- all four histories on the same absolute axis;
- selected-product range and endpoint marker;
- observation time, selected family, range, and hourly cadence;
- a restrained Soft Azure outer pocket around the actual share artifact.

The API reverse was retired after the interaction audit. Share is now a direct
action from the chart or Work drawer. It sends the PNG through the native share
sheet where available and falls back to a download plus copied standalone
link. The standalone URL uses `view=share&present=card`; old `view=card` URLs
remain compatible.

## Base, Open, Work

The final card grammar is:

```text
base cover -> open chart <-> Work
                        \-> Share
```

The cover remains a small editorial object. Its source artwork is converted
into a checked-in one-bit ordered-dither derivative and tinted by the card
identity color. The expanded chart remains at the article measure.

Work replaces the decorative API flip with a source-backed publication drawer.
Its rows are derived from each public payload:

```text
read the published Gold object
prepare or align the selected series
expose the read-only public object
```

Rows disclose schema, observation window, coverage, methodology, and endpoint
state. They describe completed publication work and current object state. They
do not claim that an agent executed a task. The exact HTTPS endpoint can be
opened or copied from the drawer.

The three dithered derivatives were generated deterministically from the
existing local card art:

```text
magick INPUT \
  -resize '600x600^' \
  -gravity center \
  -extent 600x600 \
  -colorspace gray \
  -ordered-dither o8x8,2 \
  -colorspace sRGB \
  -quality 72 \
  -define webp:method=6 \
  OUTPUT.webp
```

Inputs and outputs:

```text
assets/gpu-index-signal.webp
  -> assets/work/gpu-index-dither.webp
../images/stock/logo-babbage.jpg
  -> assets/work/sandbox-cost-dither.webp
../images/stock/logo-exchange.jpg
  -> assets/work/rate-movement-dither.webp
```

## Verification

```text
npm run build:compute
node --check exemplars/compute/compute-cards.js
uv run python -m unittest tests.test_adamsioud -v
git diff --check
```

The focused AdamSioud suite passed five tests.

Browser QA covered the detail, share, and API states at 1440 by 1000 and
390 by 844 viewport overrides. Verified results:

```text
all four quote values loaded                    passed
all four history lines rendered                 passed
selected family and range persisted in URL      passed
keyboard Home/End inspection                    passed
tooltip included four nearby prices             passed
tooltip remained inside mobile chart            passed
share front and API reverse                      passed
all three article cards ready                    passed
broken images                                      none
page-level horizontal overflow                    0 px
console errors                                     none
```

## Maintenance

The source files are:

```text
external/AdamSioud/exemplars/compute/feeling_the_compute.html
external/AdamSioud/exemplars/compute/gpu-index-card.source.js
external/AdamSioud/exemplars/compute/gpu-index-card.tailwind.css
```

The checked-in `compute-cards.js` and `compute-card.css` files are generated.
Rebuild both from the AdamSioud repository root after any source change.

## Card-System Refinement

The chart pass exposed inconsistencies in the surrounding component. A second
audit treated GPU Price Index, Sandbox Cost, and Rate Movement as one card
family before adding more visualization behavior.

Changes:

- made each compact cover a keyboard-accessible opening target while retaining
  the external `Open` action;
- aligned control rails to the object edge and strengthened focus, hover, and
  press feedback without moving controls onto the artwork;
- reduced double-border and feed-icon noise while increasing critical metadata
  legibility;
- gave all three share artifacts the same themed sleeve instead of framing
  only the GPU card;
- shortened measured-height and front/API transitions so height and content
  settle together;
- introduced Geist only inside the market-card system so title and support
  copy remain legible at the article's inherited `0.8` zoom;
- enlarged compact cards and chart controls without turning them into dashboard
  panels;
- strengthened the selected D3 series, retained context lines, and tooltips
  while preserving the same public Gold contracts and calculations;
- kept the existing artwork, palette, Gold contracts, and D3 renderers
  unchanged.

The redesign and motion skills were used as review standards, not as a reason
to replace the article with a generic dark application shell. Browser checks
covered cover, detail, share, and API states on desktop and mobile. The mobile
document width matched its scroll width, all images loaded, and the console
remained clean.

## Canonical StarSling Refresh

The public StarSling repository was re-extracted before finalizing the article
copy:

```text
source commit
70a62b0154043eafb15d828f497cbd6d445fa591

accepted publication shape
4 vCPU / 8 GiB / 40 GB

retained compatible runs
8 runs over 6 calendar days
44 provider-run mean rows
141 complete replicate-indexed jobs
1,410 aligned phase rows
7 methodology generations

latest run
30322186937
6 services
72 of 72 complete jobs
720 aligned phase rows
```

The refresh rejected five older runs before silver because their allocation
shape was incompatible:

```text
29130741476  2 vCPU / 8 GiB / 20 GB
29346212440  2 vCPU / 8 GiB / 40 GB
29365910084  2 vCPU / 8 GiB / 40 GB
29472826358  2 vCPU / 8 GiB / 40 GB
29546060837  2 vCPU / 8 GiB / 40 GB
```

Commands:

```text
uv run sandbox-cost refresh-benchmark \
  --output-root /tmp/sandbox-source-audit \
  --source-ref main

uv run sandbox-cost refresh-benchmark \
  --output-root /tmp/sandbox-source-update \
  --source-ref main \
  --update-evidence

uv run sandbox-cost validate
```

The old article sentence froze seven runs and five days in HTML. The revised
card reads run count, calendar-day count, and methodology count from the
published workload contract. This keeps prose fallback useful while preventing
the next compatible upstream run from making the public card stale.

## Final Verification

Two builds over the same reviewed inputs produced the same build ID:

```text
sandbox-cost-195eec2b5be9dc8f
```

Their four public artifacts were byte-identical:

```text
sandbox-cost.json   4ea6b6b42f8ccc9e8f53f362bcc0e2e755284f4de4ca4c41ee9d5859dcee0a0c
sandbox/rates.json  5bec85d08b0bfde0dbae46a8cf41975f85ca8e2bfdd40fe9e00bd5e68ca45596
sandbox/workload.json
                    de80c1ac04b510196b6405a4cfc6a8c3323ebf122c4221c72045763ab6e6288c
sandbox/relative.json
                    8e0cc755163558244b5951b465c62805ea4848932e44f55c15d725edbb0ed591
```

The live public payload was newer than the local operational histories used for
that deterministic test. The checked-in workhouse fallback was therefore
promoted from the exact live pipeline artifact rather than from a partial local
rebuild that lacked VM discovery history.

Final checks:

```text
npm run build:compute                                      passed
node --check exemplars/compute/compute-cards.js            passed
uv run python -m unittest discover -s tests -v             98 passed
uv run sandbox-cost check-public --url <public-payload> \
  --max-age-hours 2.5                                      passed
git diff --check                                            passed
```

Browser QA covered GPU cover/detail/share/API, sandbox workload detail, and
relative-rate detail at 1440 by 1000 and 390 by 844. Keyboard opening moved
focus to Close, all public rows loaded, the workload card reported eight runs
over six days, document width matched viewport width, and browser logs were
empty.

## Editorial Object Pass

The three compact cards were subsequently centered in the article and each was
given an explanatory passage underneath. An initial pass allowed the open
analytical state to occupy 80 percent of the visible browser width. Visual
review showed that this overpowered the article, so the breakout was removed:
the open chart now matches the normal text measure on desktop and mobile. The
compact cover and share artifact retain their independent sizes.

The moving cover feeds are now display-only. Feed items may still carry source
URLs in the internal view model, but the shared feed renderer ignores links
unless a caller opts in explicitly. This prevents market observations from
behaving like disguised API controls while retaining explicit source and API
actions inside the expanded objects.

Desktop and mobile checks confirmed all three compact objects were centered,
the expanded chart matched the article measure, document scroll width equalled
client width, and the browser error log remained empty.

## Embroidered Masthead

The old tracked gray `THE COMPUTE BAZAAR` line under the five engravings was
replaced with a live embroidered wordmark. An initial dark-fabric panel made
the visual read as a second card, so that approach was discarded. A second
pass placed three equal labels around the images; browser review showed that
it lacked hierarchy. The retained lockup uses a small Sage Green `THE`, a
dominant Soft Azure `COMPUTE`, and a Warm Sand `BAZAAR`, with the engraving row
crossing the middle in front.

The implementation preserves the supplied two-texture methodology:

```text
art RGB      pre-colored patch, border, and ink
field RGBA   coverage, ink, merrow ring, stitch angle
weave        local 512 x 512 grayscale bump texture
shader       relief, satin direction, contact shadow, cursor relighting
```

The canvas is transparent outside the stitched shapes. This removed the black
rectangle while preserving the patch material and contact shadows. The normal
article H2 remains the semantic title.

Texture provenance:

```text
source
https://pub-58a0dfd4417141169bd84ab545cd7830.r2.dev/vault/embroidery-weave.webp

sha256
b9e5bde9c84106518abc183e9cc3ccf799aad9190b94c725a64c2e6c2237f5ab
```

Operational behavior:

- waits for the loaded Geist face before building glyph masks;
- defers repeat builds to idle time after resize;
- pauses animation offscreen and while the document is hidden;
- uses a static frame for reduced-motion preferences;
- retains plain fallback text until the first successful WebGL paint;
- uses a local asset and ships inside the existing static compute bundle.

## Masthead Image Set

The original five inverted engravings were replaced with the supplied market
and compute photographs:

```text
vaulted public hall
open-outcry trading floor
quantum computer installation
street market
bazaar negotiation
```

The images were downloaded once, converted to local WebP files, and cropped
inside the existing square panel geometry. The larger trading-floor and
quantum-computer sources were capped at 900 pixels wide; the smaller sources
were not upscaled.

A first-pass random palette would have made the row visually noisy. The
retained treatment is symmetrical:

```text
Sage Green -> Warm Sand -> Soft Azure -> Warm Sand -> Sage Green
```

The image is grayscale-multiplied into its panel color. Every panel uses a
one-pixel ink border, a Soft Linen separation ring, and a narrow matching outer
edge. No hover transform was added because the WebGL thread relighting already
provides the masthead's motion.

The exact source URLs are recorded in the component README. Three were supplied
through Google thumbnail proxies and therefore still require original publisher
and license resolution before final external publication.

A final composition pass increased the panel row from 560 to 600 CSS pixels
and reduced desktop gaps from 22 to 14 pixels and mobile gaps from 12 to 8
pixels. A brief attempt to restore the original angled Soft Linen ribbon made
the new tinted frames feel over-layered, so the ribbon was removed again. The
image treatment and crops were left unchanged.

## Work View And Share Card

The final interaction audit removed the old API reverse and kept four clear
behaviors:

```text
base cover
open analytical view
Work publication record
Share PNG and standalone link
```

The `compute-card-work.js` primitive renders a horizontal activity reel from
each public Gold payload. Selecting a stage updates one compact inspector below
the reel. The browser does not invent a task stream. GPU stages report the
benchmark schema, retained observation window, four-family preparation,
constituent coverage, methodology, history count, cadence, and endpoint.
Sandbox stages report retained StarSling batches, comparable jobs, service
coverage, cost basis, and endpoint. The common-start card reports its three
aligned series, observation window, DataFusion query output, coverage floor,
and endpoint.

The Share action was restored as a visible fourth state after the direct-export
version proved too implicit. The share view centers the exact 16:9 SVG inside a
small tinted publication sleeve. Readers can return to Chart, open Work, copy a
standalone link, or export the previewed image. API and provenance details stay
inside Work.

The cover and Work artwork use local 600 by 600 ordered-dither WebP derivatives.
Their combined transfer size is about 486 KiB. The public source images remain
the provenance authority; the derivatives are presentation assets.

Final browser checks:

```text
desktop cover, detail, Work, standalone share             passed
390 x 844 detail and Work media-query pass                passed
mobile document horizontal overflow                       0 px
broken images                                              0
three repeated detail/Work transitions                    passed
stale inline transition height/position                    none
Work disclosure expansion at 390 px                       passed
Share export button reached Saved                         passed
GPU Work history                                           1,007 observations
GPU Work current coverage                                  28 providers/offers
sandbox Work                                               8 batches / 6 services
relative Work                                              113 observations
```

Commands:

```text
npm run build:compute
node --check exemplars/compute/compute-cards.js
uv run python -m unittest \
  tests.test_adamsioud \
  tests.test_gpu_market_core \
  tests.test_sandbox_cost -v
uv run sandbox-cost check-public \
  --url https://d3n0n6h709c83f.cloudfront.net/sandbox-cost.json \
  --max-age-hours 2.5
git diff --check
git -C external/AdamSioud diff --check
```

Results:

```text
relevant tests                                              76 passed
public snapshot freshness                                   passed
partial public source runs                                  none
```

## Four-State Card Follow-Up

The later interaction pass made the four states explicit instead of treating
Share as an immediate export:

```text
cover -> chart -> share
               -> work
```

Share now previews the exact 16:9 SVG that will be exported. Its rail offers
Chart, Work, Publication link, Share image, and Close. The GPU publication link
comes from the public Gold card contract and identifies an immutable
Open Graph page for the selected family and range. Until that contract reaches
the browser, the control falls back to the existing standalone article URL.
The sandbox workload artifact no longer
uses the generic `SAME SOFTWARE JOB` corner label, leaving the measured cost,
unit, service ranges, observation time, and completed-job count to carry the
card.

The hourly Gold export writes 12 GPU publication pairs: four GPU families by
three ranges. Every pair contains a crawler-readable HTML document and a
1600-by-900 PNG generated from the same compact Gold series used by the live
D3 card. Revisioned URLs prevent a later hourly run from changing a shared
publication underneath a social cache.

Work was tightened around a source-backed activity reel. The three retained
publication stages form a horizontal tablist, and one inspector shows the
selected stage's real payload fields. Text sizes were raised from chart-
annotation scale, long stage names wrap, arrow-key navigation works, and the
reel scrolls without exposing a scrollbar on narrow screens. No synthetic
agent events were introduced.

Follow-up browser checks:

```text
GPU cover, chart, share, and Work states                    passed
sandbox share without generic corner tagline               passed
common-start Work and share states                          passed
detail -> Work -> share repeated transition loop            passed
stale inline transition height/overflow                     none
standalone 16:9 share artifact                              passed
390 x 844 Work and share layouts                            passed
document horizontal overflow                               0 px
broken images                                              0
```

Follow-up verification:

```text
npm run build:compute                                      passed
node --check exemplars/compute/compute-cards.js            passed
uv run python -m unittest \
  tests.test_adamsioud \
  tests.test_gpu_market_core \
  tests.test_sandbox_cost -v                               76 passed
git diff --check                                           passed
git -C external/AdamSioud diff --check                     passed
```

## Production Publication Rollout

The production Windmill worker was rebuilt and moved from the 28 July card
release to:

```text
compute-bazaar-windmill-worker:2026-07-30-gpu-publications-v1
image sha256:34c3439e7989c892428085d88eb312300a8b685ddb53e62d9683a76aa85b4391
```

Only `windmill_worker` was recreated. PostgreSQL, the Windmill server, AutoMQ,
and the existing hourly schedule remained running. The health endpoint reported
a healthy database and live workers after the change.

The first synchronous smoke request reached the client's old 300-second timeout
and Windmill canceled it when the HTTP connection closed. This was a smoke
client defect, not a provider or publication failure. The client allowance is
now 900 seconds, and the production-equivalent verification was resubmitted
asynchronously:

```text
Windmill job     019fb030-0395-57cf-0060-0ee8604817d4
market run       market-publication-smoke-20260730b
duration         383,839 ms
result           success
```

That run published all 12 family/range page-image pairs. The verified H100
all-history publication was:

```text
https://d3n0n6h709c83f.cloudfront.net/publications/gpu-index/h100/all/gold-market-20260729t230000-a5df46ac-0e1dfe874c.html
```

Production checks:

```text
HTML status/content type                                  200 / text/html
PNG status/content type                                   200 / image/png
HTML and PNG cache policy                                 one-year immutable
Open Graph image dimensions                              1600 x 900
Twitter card                                              summary_large_image
live-chart return state                                   H100 / all / detail
browser image natural size                               1600 x 900
browser horizontal overflow                              0 px
Windmill job                                              success
full Python suite                                         101 passed
```

## X Large-Image Compatibility

Telegram and Discord rendered the first publication image, while X read its
title and description but displayed a generic document tile. Direct
Twitterbot requests returned HTTP 200 for both the HTML and PNG, ruling out
authentication, robots, TLS, and CloudFront access as the immediate cause.

The successful TradingView publication used a stricter social profile than
the first Compute Bazaar exporter: an opaque near-2:1 RGB PNG, a declared
1200-by-630 Open Graph frame, and an explicit `twitter:url`. The publication
exporter now uses that compatibility profile:

```text
publication schema        compute_bazaar_publication_v2
publication path          publications/gpu-index/v2/...
social image              1200 x 630 opaque RGB PNG
card metadata             Open Graph + summary_large_image + twitter:url
```

The live 1600-by-900 share download is unchanged. Social render settings and
schema version are included in the publication revision hash. This is
important operationally: X caches publication cards aggressively, so a
renderer fix must generate a new immutable URL instead of mutating the old
cached page.
