# First-Party Publication Domain

Date: 2026-07-30

## Decision

Use `https://bazaar.adamsioud.com` as the canonical public origin for Compute
Bazaar data objects and frozen chart publications.

`charts.adamsioud.com` was rejected because the public surface already includes
JSON data, publication pages, images, and future market tools. The shorter
`bazaar` name is branded without tying the hostname to one rendering format.
The original CloudFront hostname remains a working compatibility endpoint.

## Infrastructure

The public-dashboard Terraform stack now:

- requests a DNS-validated ACM certificate in `us-east-1`;
- exposes the ACM validation CNAME as an output;
- activates the CloudFront alias only after an explicit second-phase toggle;
- uses TLS 1.2 or newer for the custom hostname;
- exposes the final DNS CNAME target and canonical data base URL.

The two-phase apply prevented a period where DNS pointed at a distribution
without a matching certificate. The final state was checked with:

```sh
terraform -chdir=infra/aws/public-dashboard plan -detailed-exitcode
```

Result: no changes.

Namecheap must retain both CNAME records:

1. the generated ACM validation record, for certificate renewal;
2. `bazaar` to `d3n0n6h709c83f.cloudfront.net`, for public routing.

## Publication Semantics

The publication generator now defaults to `https://bazaar.adamsioud.com`.
Windmill passes the same value explicitly through a non-secret
`public_base_url` variable.

The public base URL and article URL are part of the immutable publication
revision material. A hostname or canonical-article change therefore creates a
new object path instead of overwriting a previously cached publication page.
Old CloudFront publication URLs remain valid.

The public article and its operator notes now use the first-party hostname for
GPU, sandbox-rate, and relative-rate objects. Historical journal entries keep
their original URLs as contemporaneous evidence.

## Deployment

Worker image:

```text
compute-bazaar-windmill-worker:2026-07-30-first-party-domain
```

The worker was rebuilt on the private EC2 runtime, the worker container alone
was recreated, and the Windmill market script, variable, and hourly schedule
were upserted. The schedule remains:

```text
0 0 * * * *
```

One end-to-end smoke used:

```text
market-first-party-domain-20260730T0436
```

Gold, dashboard export, sandbox cost, publication generation, and the market
manifest completed. Lium and Cloud GPU Prices timed out upstream, so the run
correctly finished with `warning`; neither failure was caused by DNS,
CloudFront, or publication generation.

## Verification

- `https://bazaar.adamsioud.com/gpu-benchmark/h100.json`: HTTP 200.
- The generated publication manifest contains 12 first-party page and image
  URLs.
- A Twitterbot request to the H100 publication page returns HTTP 200.
- Canonical, Open Graph, Twitter, image, and data metadata all use
  `bazaar.adamsioud.com`.
- Desktop 1440 x 900 and mobile 390 x 844 article checks showed no horizontal
  overflow.
- The article console reported no warnings or errors.
- The local article proxy exposed the new first-party publication URLs.
- `uv run python -m unittest discover -s tests`: 104 tests passed.
- Ruff formatting and focused lint checks passed.

## Limitation

A first-party hostname improves clarity, continuity, and domain reputation, but
it cannot force X direct messages to render a large preview. Social unfurl
behavior remains controlled by each client and its cache. The publication page
now presents the strongest standards-compliant metadata we control.

## Human-Readable Publication Routes

The first first-party links still exposed two implementation details:

```text
publications/gpu-index/v2/b200/all/gold-market-...html
```

`v2` described the renderer schema, and `gold-market-...` described an internal
pipeline run. Neither helped a reader understand the shared object. Newly
generated links now use the shared publication route contract:

```text
publications/{card}/{subject}/{view}/{observed-at}-{content-digest}.html
```

The GPU example is:

```text
publications/gpu-index/b200/1-day/2026-07-30-0505-utc-c12a9c8572.html
```

The corresponding payload record names the GPU, selected range, displayed
value, percentage change for that range, observation time, and stable
publication ID. Open Graph and X titles now include the GPU name, current
GPU-hour value, and selected-period change. Full-history links state the first
retained observation date rather than claiming an undefined all-time period.

The route builder is card-neutral. Future sandbox, relative-price, activity,
and compute-deal publications can provide their own card, subject, and view
segments while retaining the same immutable timestamp-plus-digest rule. Old
`v2` objects remain untouched and valid.

### Production rollout

The shared route contract was deployed in:

```text
compute-bazaar-windmill-worker:2026-07-30-publication-routes-v3
sha256:1359dbf5e86621b87fa652163e87929a9291a697d2565af23aa1e2cc7d360386
```

The production smoke run was:

```text
market-publication-routes-v3-20260730T0543
```

Gold, dashboard export, sandbox-cost processing, VM-capacity processing, and
publication generation completed. The overall run was a warning because Cloud
GPU Prices returned repeated HTTP 500 responses and Thunder Compute returned
HTTP 525. Sixteen other providers completed, including Vast, Lium, Prime,
Runpod, and the maintained rate-card sources.

The generated manifest uses `compute_bazaar_publication_v3` and
`compute_bazaar_publication_route_v1` and contains 12 immutable publications.
The checked B200 one-day publication is:

```text
https://bazaar.adamsioud.com/publications/gpu-index/b200/1-day/2026-07-30-0505-utc-c12a9c8572.html
```

It publishes `$6.11/GPU-hour`, `Up 0.9% over 1 day`, 13 contributing providers,
and the exact observed timestamp. Browser inspection confirmed the canonical
URL, Open Graph image, `summary_large_image` metadata, live-chart and data
links, no horizontal overflow at the checked desktop viewport, and no console
warnings or errors. The previous `v2`/run-ID URL returned HTTP 200 after the
rollout.

Verification for this rollout:

- `uv run python -m unittest discover -s tests`: 106 tests passed.
- Focused Ruff checks passed for the route contract, publication generator,
  and publication tests.
- `git diff --check` passed.
- Whole-repository Ruff still reports seven unrelated pre-existing findings in
  `src/the_compute_bazaar/tangents/`.

The temporary local SSH tunnel was closed after verification, and the
single-IP TCP/22 security-group rule added for this deployment was revoked.

## Next Refresh

No separate domain job is required. Every hourly market run receives
`public_base_url` from Windmill, writes new first-party publication URLs, and
retains the old immutable objects. If the hostname changes again, update the
Terraform alias, Windmill variable, article data base, and publication revision
inputs together.
