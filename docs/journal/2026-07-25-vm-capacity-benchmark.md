# VM Capacity Benchmark Journal

Date: 25 July 2026

## Later Revision: Continuous Seven-Vendor Cohort

The first release below established a four-provider cohort, but its silver
history retained only price-change events. That made an hourly job look like a
one-point chart whenever catalogs stayed unchanged. Before treating that
series as established history, the contract was revised:

```text
each successful hourly source check
  -> one immutable bronze capture
  -> one normalized silver observation

each timestamp with all seven exact vendor observations
  -> one DataFusion gold median, mean, p25, and p75 point
```

An unchanged catalog price is still a new observation of the market at a new
time. Repeating the same source and timestamp is idempotent. A conflicting
payload at an already retained timestamp fails rather than replacing history.
Manifests now expose `history_observation_count`; the older
`history_event_count` field remains temporarily as a compatibility alias.

The publication cohort is now `public_vm_4vcpu_8gib_v2`, with methodology
`seven_vendor_exact_shape_hourly_median_iqr_v1` and fixed membership:

| Provider | Exact selection | Initial audited native rate |
| --- | --- | ---: |
| Akamai Linode | `g6-standard-4` | $0.072/hour |
| Vultr | `vc2-4c-8gb` | $0.055/hour |
| Scaleway | `BASIC3-X4C-8G`, Paris | EUR 0.079001/hour |
| Microsoft Azure | `Standard_F4s_v2`, West Europe | $0.194/hour |
| Amazon EC2 | `c7i.xlarge`, Paris | $0.2121/hour |
| OVHcloud | `d2-8.consumption`, France catalog | EUR 0.0372/hour |
| Oracle Cloud | `VM.Standard.E4.Flex`, 2 OCPU + 8 GB | $0.062/hour |

AWS is selected through the official Price List API and validated as Linux,
shared tenancy, on-demand, four vCPU, and 8 GiB in `eu-west-3`. OVHcloud is an
active hourly Linux catalog plan with four cores, 8 GB, and 50 GB local NVMe.
Oracle is composed from official PAYG meters:

```text
2 OCPU * $0.025/OCPU-hour
  + 8 GB * $0.0015/GB-hour
  = $0.062/hour
```

The collector also records an Akash request estimate for four CPU units,
8 GiB, and 20 GiB storage. The first checked response was $30.46/month, or
about $0.04173/hour when divided by 730. It remains
`marketplace_indication`, not a vCPU claim, bid, lease, executed price, or
member of the seven-vendor median.

The old `public_vm_4vcpu_8gib_v1` gold query remains for audit. It is not
relabeled or backfilled. The v2 graph begins at its first complete seven-source
hour. This is what "do not quietly change the historical median" means: a
membership change gets a new cohort and methodology, while all prior source
observations remain what they originally were.

At release time, v2 therefore has one honest point rather than an invented
line. Each subsequent complete Windmill hour appends seven source observations
and one gold cohort point. A catalog that returns the same price as the prior
hour still contributes a new observation because it was checked again at a new
time.

Additional source audit:

- DigitalOcean, Hetzner, Google Cloud, Leaseweb, and UpCloud require a useful
  API credential or a more involved catalog contract before they can become
  maintained hourly inputs.
- Real Akash bids require deployment and escrow context; the public pricing
  endpoint is only an estimate.
- Golem marketplace proposals require a running Yagna client and app key.
- Spare Cores is useful for secondary validation, but its current terms do not
  permit republishing or reassembling its Navigator data into a competing
  comparison database without permission, so it is not an input.

New maintained paths:

```text
raw/sandbox-cost/vm-capacity-discovery/source=<source>/...
lake/sandbox_cost/silver/vm_capacity_discovery_history.parquet
lake/sandbox_cost/silver/vm_capacity_expanded_history.parquet
lake/sandbox_cost/silver/vm_capacity_marketplace_history.parquet
lake/sandbox_cost/gold/vm_capacity_expanded_rate.parquet
lake/sandbox_cost/gold/vm_capacity_observed_rate.parquet
```

The Windmill market heartbeat uses one `observed_at` value for both source
collectors, so the seven rows can form one complete hourly cross-section.
Source failures remain isolated, but an incomplete timestamp does not produce
a new seven-vendor gold point. The current last-known source rows remain
available with their own check times.

## Objective

Add the infrastructure below managed code sandboxes to the maintained
Compute Bazaar story. The publication should show two distinct fixed cohorts:

```text
public VM offer rate
  -> underlying four-vCPU, 8 GiB capacity

managed sandbox rate
  -> processor-and-memory rate for the audited sandbox request
```

The purpose is not to claim that sandboxes are a simple resale of VMs. It is to
give the reader an observable substrate reference before discussing managed
runtime, measured workload time, and marginal cost.

## Source Audit

Four official, unauthenticated, machine-readable catalogs expose an exact
four-vCPU, 8 GiB selection with enough metadata to validate the shape:

| Provider | Source selection | Shape check | Public hourly price at first check |
| --- | --- | --- | ---: |
| Akamai Linode | `g6-standard-4` | 4 vCPU, 8192 MB | $0.072 |
| Vultr | `vc2-4c-8gb` | 4 vCPU, 8192 MB | $0.055 |
| Scaleway | `/compute/basic3_x4c_8g/run_fr-par-2` | 4 shared vCPU, 8 GiB | EUR 0.079001 |
| Microsoft Azure | `Standard_F4s_v2`, `westeurope`, Linux consumption | 4 vCPU, 8 GiB | $0.194 |

Official sources:

- [Akamai Linode Types API](https://techdocs.akamai.com/linode-api/reference/get-linode-types)
- [Vultr Plans API](https://docs.vultr.com/reference/vultr-cli/plans/list)
- [Scaleway Public Catalog API](https://www.scaleway.com/en/developers/api/product-catalog/public-catalog)
- [Azure Retail Prices API](https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices)
- [Azure Fsv2 machine specification](https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/compute-optimized/fsv2-series)

The first retained production-like source check was
`2026-07-25T05:25:57.740763+00:00`. The latest ECB EUR/USD reference rate was
1.1377, making the observed Scaleway comparison value approximately
$0.089879/hour. The resulting fixed-cohort cross-section was:

```text
median          $0.08093971885/hour
p25             $0.06775/hour
p75             $0.115909578275/hour
member count    4
```

The current fixed sandbox cohort median was $0.4806/hour, producing an observed
cohort-rate ratio of approximately 5.94. That ratio is descriptive only.

## Source and Product Differences

Storage cannot be normalized away without inventing a product:

- Linode includes 160 GB.
- Vultr includes 160 GB SSD.
- Scaleway storage is separate.
- Azure includes 32 GiB temporary storage; OS and persistent disks are
  separate.

The table and payload retain these distinctions. CPU generation, tenancy,
burst behavior, region semantics, network, egress, SLA, and provisioning API
also differ. The cohort therefore measures observed offer rates for one exact
headline shape, not equal delivered work.

Scaleway requires an FX conversion. The native EUR value, ECB reference rate,
FX effective date, and USD result are all retained. An FX move can create a
new event even when the native offer is unchanged.

## Decisions

1. Use the term “observed VM offer rate,” not “CPU price.”
2. Fix membership at four providers for this first history. Provider discovery
   can expand separately without rewriting the cohort.
3. Require exactly four vCPUs and 8 GiB. Reject approximate or burst-credit
   shapes.
4. Use Linux public on-demand offers only. Exclude spot, reservations,
   commitments, and promotions.
5. Keep one declared reference region when a catalog is regional.
6. Retain every raw source check with retrieval time and checksum.
7. In the original v1 release, append a silver event only when price, native
   currency/FX, shape, location, storage treatment, or inclusion semantics
   changed. The later v2 revision above supersedes this with one observation
   per successful hourly check.
8. Do not backfill history from undated current catalogs. The line starts with
   the first automated check.
9. Compute current, median/IQR history, and VM/sandbox comparison through named
   DataFusion SQL queries.
10. Isolate one provider failure, retain the last validated row, and publish a
    warning. Never silently describe an incomplete cohort as complete.
11. Plot the VM and sandbox cohorts on a common raw USD/hour log axis because
    the units match but their levels differ materially.
12. Show a point and p25-p75 whisker until VM history contains a real second
    event. Do not draw a fake historical line.

## Discarded Approaches

- A generic “CPU price” line was rejected because vCPU performance and tenancy
  are not standardized.
- A VM/sandbox “markup” or “margin” was rejected. Public rates do not reveal
  provider cost, utilization, orchestration overhead, support, or realized
  revenue.
- A simple average across arbitrary plans was rejected. Exact shape and fixed
  membership are necessary for interpretable changes through time.
- AWS and Google Cloud were deferred from cohort v1 because a stable,
  unauthenticated exact public-rate selection requires more catalog and region
  machinery than this first four-member product.
- DigitalOcean, Hetzner, and UpCloud were not added because their useful
  machine-readable catalog paths require authentication or did not expose the
  same complete public contract.
- Historical points were not reconstructed from current price pages or search
  snippets.
- Storage was not assigned an imputed dollar value.
- The managed-sandbox cohort was not replaced. VM offers answer a different
  question and now sit beneath it.

## Layer Contract

Bronze:

```text
raw/sandbox-cost/vm-capacity/
  provider=<provider>/date=<date>/run_id=<run>/...
```

Every response body is immutable and accompanied by retrieval metadata and a
checksum manifest.

Silver:

```text
lake/sandbox_cost/silver/vm_capacity_offer_history.parquet
lake/sandbox_cost/silver/vm_capacity_current.parquet
lake/sandbox_cost/silver/vm_capacity_source_manifest.json
```

Silver stores native and USD prices, FX, exact shape, location, storage,
purchase basis, source links, first/last observed time, check count, event
order, and raw references.

Gold:

```text
lake/sandbox_cost/gold/vm_capacity_current.parquet
lake/sandbox_cost/gold/vm_capacity_fixed_rate.parquet
lake/sandbox_cost/gold/vm_sandbox_current_comparison.parquet
```

The public `sandbox-cost.json` v4 contains sanitized current rows, fixed-rate
history, source-check status, and the current cohort comparison. Raw S3
references and private manifests are removed.

## Formulas

```text
vm_fixed_median =
  median(exact-shape fixed-member USD hourly offers)

vm_p25, vm_p75 =
  quantile_cont(offer prices, 0.25), quantile_cont(offer prices, 0.75)

observed_rate_ratio =
  fixed sandbox cohort median / fixed VM cohort median
```

The ratio does not estimate gross margin. The common chart preserves raw
USD/hour and uses a log scale only to make both bands legible.

## Commands

```sh
uv run sandbox-cost refresh-vm-capacity \
  --output-root data/lake/sandbox_cost \
  --raw-root data/raw

uv run sandbox-cost build \
  --output-root data/lake/sandbox_cost \
  --dashboard-output-root data/dashboard/compute-bazaar \
  --gpu-history-ref data/lake/sandbox_cost/silver/gpu_benchmark_history.parquet \
  --vm-capacity-history-ref data/lake/sandbox_cost/silver/vm_capacity_offer_history.parquet \
  --vm-capacity-current-ref data/lake/sandbox_cost/silver/vm_capacity_current.parquet \
  --vm-capacity-manifest-ref data/lake/sandbox_cost/silver/vm_capacity_source_manifest.json

uv run sandbox-cost query \
  --output-root data/lake/sandbox_cost \
  --query vm-sandbox-current \
  --limit 10

uv run python -m unittest \
  tests.test_sandbox_cost \
  tests.test_vm_capacity \
  tests.test_adamsioud -v

node --check external/AdamSioud/exemplars/compute/sandbox-cost.js
```

## Frontend and Visual QA

The AdamSioud article now introduces the infrastructure and managed-runtime
cohorts in one narrative block:

- `CPU CAPACITY PRICES, checked hourly` shows source freshness.
- Four top values separate VM median, sandbox median, observed ratio, and
  source status.
- “Fixed cohorts through time” uses one log-scaled USD/hour chart with distinct
  VM and sandbox bands.
- A compact VM ledger and audit table expose provider, exact plan, location,
  native/USD rate, storage treatment, first/last observation, and source.
- Pointer and keyboard tooltips report median, p25-p75, membership, and
  observation semantics.

Desktop inspection at 1280 x 720 and mobile inspection at 390 x 844 found no
page-level horizontal overflow. Audit tables scroll within their own
containers. The VM one-point history renders as a whisker and point rather
than implying prior observations. Browser console inspection returned no
warnings or errors.

## Recurrence

`market_hourly` now refreshes the fixed VM cohort before building sandbox gold.
It preserves raw checks and carries the VM refs into the market-run manifest.
The daily `sandbox-cost-sources` workflow also performs a temporary live schema
and exact-shape check, then runs focused tests. The daily check does not write
durable history; Windmill owns that role.

Managed-sandbox rate cards remain manually reviewed. StarSling benchmark
evidence remains commit-pinned and manually promoted after the daily source
check detects new compatible data.

## Original v1 Release Verification

The article changes were committed to AdamSioud as `87bbb80`. The recurring
pipeline, tests, workflow, documentation, and submodule pointer were committed
to The Compute Bazaar as `da41797`. Both `main` branches were pushed.

The VPC Windmill worker was rebuilt from the pushed source and recreated
without changing Postgres, Windmill server, or AutoMQ state. A real
`market_hourly` invocation completed as:

```text
market_run_id     market-vm-capacity-release-20260725T0545Z
VM source run     vm-capacity-20260725T054534Z
VM source status  ok
VM members        4
VM history events 4
sandbox build     sandbox-cost-c27eee3c8e3f7263
public schema     sandbox_cost_gold_v4
```

The run wrote VM bronze, silver, and gold objects to S3, published the public
payload, and retained its market-run manifest. CloudFront returned the v4
payload with all four rows and one current comparison row. A serialized
public-boundary check found no `s3://` URI or `raw_refs` field.

Verification completed with:

```text
ruff check                         passed
unittest discovery                71 passed
focused VM tests                  5 passed
JavaScript syntax                 passed
desktop browser                   passed
mobile browser                    passed
keyboard chart inspection         passed
production console/network logs   no errors
GitHub Pages deployment           passed
```

The production page rendered the 05:45 UTC source check, `$0.081/hour` VM
median, `$0.481/hour` managed-sandbox median, and `5.9x` observed cohort-rate
ratio. The hourly Windmill schedule remains enabled at `0 0 * * * *`.

## Continuous v2 Release Verification

The seven-vendor cohort was released as a new series rather than a rewrite of
the four-vendor observations. Its first manually triggered complete check and
the next scheduled check are:

```text
2026-07-25 06:27:29 UTC  median $0.072/hour  7 providers
2026-07-25 07:00:08 UTC  median $0.072/hour  7 providers
```

The second value is intentionally retained even though the rates were
unchanged. The history contract is one observation for every successful source
check, not one event for every price change. DataFusion emits a gold point only
when all seven direct-vendor offers share that exact check timestamp. A missing
or incompatible source therefore leaves a visible gap instead of carrying a
stale rate forward. The older v1 observations remain available as
`legacy_fixed_cohort_rate`; they are never relabeled or recomputed as v2.

The scheduled production run completed as:

```text
Windmill job       019f97f5-14cf-e904-a46e-741d97febfe3
market run         market-20260725T070008-dfd5dfc0
started            2026-07-25 07:00:08 UTC
completed          2026-07-25 07:01:38 UTC
four-source checks 12 retained observations
discovery checks   8 retained observations
v2 gold history    2 complete seven-provider points
public current     7 direct-vendor offers
marketplace        1 separate Akash indication
```

`market_hourly_hourly` is the only enabled recurring market schedule. The
standalone Vast and Lium schedules remain installed but disabled for manual
provider debugging, preventing duplicate observations and work. The public
CloudFront payload contains the two v2 points, the separate three-point v1
history, and no raw S3 reference.

Final local verification completed with:

```text
ruff check                  passed
ruff format --check         passed
unittest discovery          77 passed
JavaScript syntax           passed
git diff --check            passed
mobile browser              390 x 844, no page overflow
desktop browser             1280 x 720, no page overflow
keyboard chart inspection   latest 07:00 UTC VM observation
browser console             no warnings or errors
```

## Next Refresh

1. Inspect both VM source statuses in the hourly market-run manifest.
2. Confirm `vm_capacity_expanded_rate` gains one row per complete hourly run.
3. If a source fails, inspect its retained raw capture or schema error before
   changing the parser.
4. If a plan changes shape or disappears, do not substitute another plan
   silently; version the cohort or explicitly review replacement membership.
5. Review ECB-driven Scaleway or OVHcloud observations in native EUR and USD.
6. Keep marketplace indications separate until a source supplies a real,
   reproducible bid or executed lease with compatible shape semantics.
