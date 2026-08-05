# Public Dashboard Path

The dashboard/blog should read only public-safe JSON snapshots, not the private S3 lake.

```text
private S3 lake:
  raw/
  lake/

public dashboard prefix:
  dashboard/compute-bazaar/*.json
```

The hourly Windmill `market_hourly` job generates these files after each
successful DataFusion Gold build and writes them to the configured dashboard
prefix.

## Local Reader

The local FastAPI dashboard serves the page and proxies the selected snapshot source:

```sh
uv run compute-bazaar-dashboard
```

In `auto` mode, the server reads `COMPUTE_BAZAAR_DASHBOARD_OUTPUT_ROOT` when it
is an S3 URI. If that is not set, it infers
`s3://YOUR_BUCKET/dashboard/compute-bazaar` from
`COMPUTE_BAZAAR_LAKE_ROOT=s3://YOUR_BUCKET/lake`. Use
`COMPUTE_BAZAAR_DASHBOARD_SOURCE=local` to force the cached local JSON files.

The browser reads same-origin JSON from:

```text
/api/dashboard-snapshots/{allowlisted path}.json
```

That route is intentionally limited to the public-safe snapshot paths below. It can read from S3
for live local inspection, or from `data/dashboard/compute-bazaar/` when the source is `local`.

## Card Views

Product pages should prefer the versioned card views:

```text
market-overview.json
gpu-benchmark/h100.json
gpu-benchmark/h200.json
gpu-benchmark/b200.json
gpu-benchmark/b300.json
prime-frontier/h100.json
prime-frontier/h200.json
prime-frontier/b200.json
prime-frontier/b300.json
capacity/market-state.json
sandbox/workload.json
```

Every card uses `compute_bazaar_card_v1` and declares:

```text
card_type
card_id
as_of
observation_window
status
unit
methodology
headline
series
band
coverage
sources
drilldown_ref
data
```

The card layer is a public projection of Gold, not another source of truth. Numeric products are
calculated by the maintained DataFusion queries before publication. Each history row is serialized
once; compatibility code may reconstruct the old shape in browser memory while caches and old
workers expire. `drilldown_ref` names the larger public audit file where appropriate.

`market-overview.json` is the small article bootstrap. The four GPU benchmark files own their
family-specific price histories. Prime files own one family each, avoiding the old four-family
history duplication. The sandbox workload card contains the latest compatible
StarSling job-cost comparison; it is not a live sandbox-rate series.

### Article Card Boundary

The clean AdamSioud article renders its GPU benchmark card directly from the
four `gpu-benchmark/{family}.json` documents. Its measured-workload card reads
`sandbox/workload.json`.

The cards must not calculate replacement benchmark, cohort, workload, or
rebasing values in JavaScript. They may select a family, measure, band, or
retained time window; calculate a display-only change between two published
GPU values; and draw the published values and p25-p75 ranges.

On `www.adamsioud.com`, the card uses the CloudFront data base. On localhost, it uses the
same-origin `/api/dashboard-snapshots` route from `compute-bazaar-adamsioud`; this preserves the
CloudFront CORS allowlist and exercises the exact local snapshot allowlist.

## Audit Snapshots

```text
manifest.json
market-run.json
market-history.json
latest-index.json
featured-index.json
featured-benchmarks.json
benchmark-history.json
prime-frontier-offer-market.json
prime-frontier-offer-shelf.json
prime-h100-offer-reference.json
sandbox-cost.json
index-history.json
index-quality.json
index-constituents.json
benchmark-constituents.json
provider-comparison.json
listings-sample.json
```

These compatibility and audit files remain public-safe and are retained for lineage, operator
inspection, and old clients. They contain product/query outputs, counts, checks, and public-facing
rows. `featured-benchmarks.json` is the public strip for the current H100,
H200, B200, and B300 benchmark families. `benchmark-constituents.json` is still public-safe, but it is
for operator/product inspection rather than the minimal AdamSioud label. Its `complete` and
`row_count` fields confirm that the file contains the full current constituent set rather than the
sample used by `listings-sample.json`. These files do not contain provider API keys, Kafka
credentials, or private raw S3 refs.

`benchmark-history.json` is the compact article/chart feed. It carries the retained H100, H200,
B200, and B300 benchmark observations plus the provider-floor interquartile range and small
coverage counts. Each export merges the newest observations into the existing history, so the
hourly job does not need to rescan the full lake. Use it instead of downloading the much larger
all-product `index-history.json` on public story pages.

`prime-frontier-offer-market.json` is the compatibility public-safe Prime shelf
for H100, H200, B200, and B300. Each product carries the Prime
provider-balanced reference, wider Compute Bazaar benchmark, retained
histories, current benchmark-centered price levels, named upstream sources,
eligible configuration details, and observable lifecycle events. It removes
private S3 references and credentials. Counts are visible configurations and
distinct upstream providers, not physical GPU inventory or traded volume.

`prime-frontier-offer-shelf.json` is the smaller article contract for the H100
and H200 visible-offer card. It retains the full reference and event histories,
current configurations, stable listing and event identifiers, and public source
URLs. The card groups simultaneous entries and exits for display, while the
payload preserves the provider-level events used by tooltips and later
analysis. Each family also carries its immutable publication link. The hourly
build writes crawler-readable HTML and a 1200-by-630 social image under
`publications/prime-gpu-market/`; opening the publication hands the reader to
the standalone interactive Share/Work card.

`prime-h100-offer-reference.json` is an older compatibility projection of the H100
product from the same build. New consumers should use the family-specific card files.

`sandbox-cost.json` is the public audit payload for measured workload cost. It
contains complete jobs reconstructed from retained StarSling task phases,
service cost distributions, compatible source-run history, benchmark
provenance, and the reviewed processor-and-memory price inputs used by the
cost formula. It does not publish the archived VM cohort or sparse sandbox
rate-card research.

The build publishes one sandbox article contract:

```text
sandbox/workload.json
  latest compatible StarSling job-cost distribution, service summaries,
  retained run history, benchmark sources, and price-input sources
```

The payload declares currency, machine shape, source URLs, and cost basis. It
explicitly excludes lifecycle latency and full provider billing. Public source status and
checksums may be included, but raw private S3 refs, private manifests,
credentials, and raw response objects are removed at export. The market build
rebuilds the workload payload from maintained StarSling evidence and reviewed
service cost inputs.

`market-state.json` publishes the public-safe current cross-section plus
cumulative aggregate history for Akash CPU, GPU, memory, and storage capacity
and source-compatible occupancy rows. The article uses `available_share` for
the market-pulse capacity panes and keeps each resource's original unit. It
does not combine CPU millicores and GPU units or label available share as
processor activity.

## S3/CloudFront Shape

Use CloudFront in front of the dashboard prefix when the AdamSioud page is ready to fetch it:

```text
S3 bucket
  dashboard/compute-bazaar/*.json
    -> CloudFront distribution
      -> https://YOUR_PUBLIC_HOST/compute-bazaar/*.json
```

The browser page should use the HTTPS URL:

```text
?data=https://YOUR_PUBLIC_HOST/compute-bazaar
```

Keep `raw/` and `lake/` private. If using CloudFront Origin Access Control, grant CloudFront access
only to `dashboard/compute-bazaar/*`. A starter bucket policy is in:

```text
infra/aws/dashboard-cloudfront-bucket-policy.example.json
```

The repeatable Terraform setup lives in:

```text
infra/aws/public-dashboard/
```

It creates a CloudFront distribution with an Origin Access Control and maps the distribution root
to the S3 dashboard prefix. That means the public base URL serves files directly:

```text
https://DISTRIBUTION.cloudfront.net/manifest.json
https://DISTRIBUTION.cloudfront.net/latest-index.json
https://DISTRIBUTION.cloudfront.net/featured-benchmarks.json
https://DISTRIBUTION.cloudfront.net/sandbox-cost.json
```

Canonical publication pages omit the storage extension:

```text
https://bazaar.adamsioud.com/publications/gpu-index/h100/1-day/REVISION
```

A scoped viewer-request function maps that request to the corresponding
`REVISION.html` object. It does not rewrite publication images, JSON objects,
legacy `.html` links, or any route outside `/publications/`.

The same publication contract is used by the active public card families:

```text
publications/gpu-index/{gpu}/{range}/{revision}
publications/sandbox-cost/{view}/{measure}/{revision}
```

Each immutable page contains Open Graph and X metadata plus a frozen
1200-by-630 image. Social crawlers do not execute the page script, so they
retain that metadata and image. A human browser is immediately handed to the
matching `view=share&present=card` state in the main article. The Share control
therefore copies one URL that has both a rich social preview and the polished
interactive landing state. The public card JSON stores the publication URL,
image URL, live URL, and compact display line for every supported state.

GPU publication images are family-specific. The selected benchmark and its
observed p25-p75 provider range determine the image scale; higher-priced GPU
families do not flatten the selected line. The interactive Share card can still
show all four families as comparison context. This is a presentation
distinction only: both surfaces read the same Gold series, and the publication
renderer does not change benchmark membership or formulas. The renderer profile
is included in the immutable publication digest, so a material composition
change creates a new revision instead of changing an existing URL in place.

The Terraform stack can output the bucket policy statement without applying it. Keep
`manage_bucket_policy = false` when the bucket policy is already managed by hand, then merge the
`bucket_policy_json` output manually. Set it to `true` only when Terraform should own the whole
bucket policy.

The CloudFront distribution URL itself is safe to expose because it serves only public-safe
dashboard JSON, not raw provider evidence or lake objects. For a cleaner public surface, attach an
alias such as `data.adamsioud.com` to the distribution.

## CORS

The browser needs CORS for `GET` and `HEAD` on the dashboard JSON prefix. A starter CORS document is
in `infra/aws/dashboard-cors.example.json`.

The Terraform response headers policy allows the public AdamSioud domains plus the local
development origins used here: `http://127.0.0.1:8777` and `http://127.0.0.1:8801`.

Apply it after replacing the origin with the personal-site origin:

```sh
aws s3api put-bucket-cors \
  --bucket YOUR_BUCKET \
  --cors-configuration file://infra/aws/dashboard-cors.example.json
```

## Cache

The hourly job overwrites stable filenames. Use short cache lifetimes at first, for example 60-300
seconds, until the feed is boring. Later we can add immutable run-id snapshots as well as latest
pointers.

## AdamSioud Page

The page reads the local proxy by default:

```html
data-market-data-base="/api/dashboard-snapshots"
```

For the published site, replace that value with the Terraform `dashboard_data_base_url`, or preview
without editing HTML:

```text
https://www.adamsioud.com/exemplars/compute-bazaar/?data=https://DISTRIBUTION.cloudfront.net
```
