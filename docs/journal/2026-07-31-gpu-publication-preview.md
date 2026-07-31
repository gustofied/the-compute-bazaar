# GPU Publication Preview

Date: 2026-07-31

## Purpose

The first GPU social image showed H100, H200, B200, and B300 on one absolute
price axis. That was useful inside the interactive comparison card, but it made
family-specific links poor publication previews: the selected lower-priced
series could occupy only a few pixels of vertical movement.

This pass gives the crawler image one job: clearly summarize the GPU family
named in the publication URL.

## Decision

- Keep the interactive Share card as the four-family comparison surface.
- Render the immutable social image from only the selected family's Gold rows.
- Show the selected p25-p75 provider range as a quiet area around the line.
- Scale the plot to the selected value and range, with a minimum span for flat
  series.
- Retain the observed timestamp, current value, quoted range, range change,
  provider count, and observation cadence.
- Keep the final point unadorned. The latest value is labelled directly rather
  than marked with an ornamental dot.
- Bump the publication schema to `compute_bazaar_publication_v6` and the render
  profile to `social_png_rgb_1200x630_selected_series_v2`. Both participate in
  the content digest, so old publication URLs remain immutable.

## Methodology Boundary

No provider eligibility, normalization, family mapping, benchmark formula,
percentile, observation, or historical row changed. The p25-p75 range was
already present in the Gold card contract. The renderer only changed how those
published values are composed into a 1200-by-630 RGB image.

The preview says `observed advertised prices` because these are public quoted
offers, not completed rental transactions.

## Verification

The focused publication suite renders an image where an extreme unselected
B300 series cannot compress the selected H100 line. A pixel-level assertion
checks that the selected line retains meaningful vertical extent.

Real public H100 and B200 card payloads were also rendered locally. Both were
checked at full size and message-preview size for:

- readable value and change hierarchy;
- visible selected-family movement;
- legible provider-range band;
- unclipped axes and labels;
- correct observed time, range, and provider count;
- opaque RGB output at exactly 1200 by 630 pixels.

## Refresh

The recurring market worker calls `publish_gpu_benchmark_publications` after
the Gold cards are built. Once the worker image containing this renderer is
deployed, the next successful market run writes new v6 publication wrappers
and images. Existing v5 links continue to resolve to their frozen images.

## Production Proof

The renderer was deployed by recreating only the Windmill worker:

```text
worker image: compute-bazaar-windmill-worker:2026-07-31-selected-preview-v7
worker image ID: sha256:3b127b5061560256e8119256277dc37ea15c6a47f9998ae4f4aafa0f7cf42b37
```

Windmill, Postgres, AutoMQ, and their volumes were not recreated. The normal
04:00 UTC schedule then completed successfully:

```text
market run: market-20260731T040000-0089a993
gold run: gold-market-20260731T040000-0089a993
dashboard export: dashboard-market-20260731T040000-0089a993
status: success
provider inputs: 18
publication schema: compute_bazaar_publication_v6
```

Every provider, Gold, sandbox-cost, VM-capacity, and dashboard-export check
reported `ok`. The Stage 1 check also confirmed the hourly schedule remained
enabled and both Windmill workers were healthy.

The production H100 1-day wrapper and image were checked at:

```text
https://bazaar.adamsioud.com/publications/gpu-index/h100/1-day/2026-07-31-0401-utc-c107b6ce35
https://bazaar.adamsioud.com/publications/gpu-index/h100/1-day/2026-07-31-0401-utc-c107b6ce35.png
```

The wrapper contains literal Open Graph and X large-image metadata with the
canonical extensionless URL and the exact immutable PNG. The downloaded image
is an opaque 1200-by-630 RGB PNG and matches the selected-series composition.
