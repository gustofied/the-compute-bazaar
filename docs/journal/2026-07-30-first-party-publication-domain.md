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

## Next Refresh

No separate domain job is required. Every hourly market run receives
`public_base_url` from Windmill, writes new first-party publication URLs, and
retains the old immutable objects. If the hostname changes again, update the
Terraform alias, Windmill variable, article data base, and publication revision
inputs together.
