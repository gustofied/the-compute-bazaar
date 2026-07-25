# Compute Market State

## Question

Can Compute Bazaar calculate a defensible hourly rented-capacity measure from
the provider data it already collects?

Yes, but only for sources that expose both a rented numerator and a matching
total rentable denominator. Availability, rental occupancy, and hardware
activity remain separate measurements.

## Source Audit

The live source audit on 25 July 2026 found:

- Akash `/v1/providers` reports active, available, pending, and total CPU, GPU,
  memory, ephemeral-storage, persistent-storage, and aggregate-storage
  capacity for each provider. Official documentation defines active GPU units
  as currently leased and active inventory as consumed by deployments.
- Akash `/v1/gpu-prices` reports model-level available and total GPU units. It
  does not split unavailable model units into active and pending.
- Clore `/v1/marketplace` reports a server-level `rented` boolean, documented
  as rented on demand. The measurement is therefore server weighted and
  excludes the separate spot-order state. Its official API contract requires
  an `auth` header, so the recurring connector is enabled only with
  `CLORE_API_KEY`.
- RunPod exposes stock status and deployable bundle sizes, not total fleet.
- Prime Intellect exposes upstream provider and stock/configuration data. The
  returned configuration set is a denominator for configuration availability,
  but not an independent physical-fleet denominator.
- Hyperstack exposes overlapping deployable configurations. The safe count is
  a maximum deployable GPU-unit lower bound, not a sum or total fleet.
- Current VM and managed-sandbox sources expose prices and workload timing, but
  no comparable public rented-and-total fleet denominator.

Live parser audit:

```text
Akash  117 active / 372 total GPU units = 31.45% rental occupancy
Clore  891 rented / 2,064 public servers = 43.17% on-demand rental occupancy
```

These values are not pooled. They use different units and market scopes.

## Data Contract

Bronze retains the complete provider response and source URLs. Silver writes
one `ComputeMarketState` row per source-defined observation with:

```text
measurement_kind
measurement_scope
unit
rented_units
available_units
pending_units
total_units
rented_share
available_share
numerator_definition
denominator_definition
source_connector
source_role
source_url
raw_ref
methodology_version
```

Gold has two products:

```text
fact_compute_market_state
fact_compute_market_state_history
```

The first is the current cross-section. The second is cumulative and
deduplicates by observation ID while retaining the original source run and
gold-build provenance. Repeated unchanged observations remain history because
an hourly state observation is not merely a change event.

The DataFusion query is:

```sh
uv run gpu-prices operator-query compute_market_state --version v1 --limit 200
```

## Aggregator Rule

Prime Intellect preserves its upstream provider in `provider` and uses
`source_connector=prime_intellect`. If the same provider, GPU product, and
measurement kind also exist through a direct connector, the Prime row is kept
but marked `aggregation_eligible=false` with
`matching_direct_provider_source`. This prevents RunPod-through-Prime from being
added to direct RunPod stock.

## Visual Contract

The public article and operator dashboard show:

1. Current source-specific rental occupancy.
2. Hourly occupancy history on a shared percentage scale, with unit and scope
   disclosed per series.
3. A separate availability ledger for sources without a fleet denominator.

The page does not call these values processor utilization, transaction volume,
or demand. The source numerator and denominator remain visible in tooltips and
method notes.

## Backfill Decision

Retained Akash bronze before this change contains model-level available and
total fields, so model availability can be reconstructed. It does not contain
the providers endpoint and cannot support historical network rental occupancy.
The honest network occupancy series therefore begins with the first new
two-endpoint capture. No past rented values are inferred from missing listings.

## Verification

- Live Akash and Clore ingests completed against their current source schemas;
  the Clore connector now requires its documented read credential.
- Bronze, silver state Parquet, gold current, cumulative gold history, public
  JSON, and DataFusion operator query were exercised locally.
- Focused tests cover formulas, source scope, direct/aggregate preference,
  cumulative history, and dashboard export.

## Production Release

The active Windmill worker is:

```text
compute-bazaar-windmill-worker:2026-07-25-market-state-v5
sha256:19f7974e5c2a7e5110e80cd3fafe172bb58a1de0d26266c3cbc150d287a2482f
```

Two full manual release runs completed successfully:

```text
market-market-state-release-20260725T1855
market-market-state-release-20260725T1858
```

The next scheduled observation completed as:

```text
market-20260725T190000-cb6a7212
gold-market-20260725T190000-cb6a7212
```

All 18 scheduled provider/check stages, Kafka publication, gold build, S3
publication, sandbox and VM updates, and dashboard export reported `ok`. The
Windmill schedule remains enabled at `0 0 * * * *`, which runs at the start of
every hour.

After correcting the Clore authentication boundary, the final release run was:

```text
market-state-final-20260725T1928
gold-market-state-final-20260725T1928
```

All 17 configured providers and every Kafka, gold, S3, VM, sandbox, and
dashboard stage reported `ok`; the market run status was `success`.

The public-safe payload is:

```text
https://d3n0n6h709c83f.cloudfront.net/market-state.json
```

The final export contained 46 current occupancy/availability rows and eight
aggregate occupancy history rows. Akash remains current; Clore's earlier,
source-backed observations remain historical until a key is configured. The full
per-model current and historical data remains in gold; public history is limited
to `ALL_GPU` rental-occupancy rows so the article does not grow by roughly 85
model rows every hour.

The existing GPU benchmark history was revalidated after publication: 910
manifests and 3,205 rows covering 18 June through 25 July remained intact.

## Visual QA

The AdamSioud article was checked at desktop and 390 x 844 mobile widths:

- no document-level horizontal overflow;
- current occupancy cards and availability rows stack cleanly;
- the D3 history chart renders every published hourly point;
- pointer tooltips stay within the viewport and use plain-language definitions;
- keyboard focus exposes an accessible label for each chart point;
- no browser console errors or warnings.

The local operator dashboard was restarted from the project environment and
verified against its FastAPI S3/local proxy. It rendered the same six history
points during initial QA; the final payload now contains eight history points
and uses the same chart contract.

## Next Refresh

The scheduled worker now performs the refresh. For a manual end-to-end run:

```sh
uv run gpu-prices market-hourly
uv run gpu-prices operator-query compute_market_state --version v1 --limit 200
uv run --with pytest pytest tests
```

Do not synthesize historical rental occupancy from old Akash model
availability. A source must expose the matching rented numerator and total
denominator in the captured response before an occupancy row can be admitted.

## 26 July Capacity Correction

Inspection of the installed Prime CLI showed that its JSON `total_count`
describes returned configurations after CLI filtering/grouping. Prime rows now
store available configurations divided by all returned configurations for the
same upstream provider and GPU product. They remain availability-pressure
observations, not rented GPU-unit occupancy.

Akash normalization now also writes aggregate active/total rows for CPU,
memory, total storage, ephemeral storage, and persistent storage. The same
provider response was already retained in bronze; the new rows make those
source fields queryable in silver and gold without frontend arithmetic.

The public history allowlist now includes only aggregate CPU, GPU, memory, and
storage resource types. Per-model history remains in gold.

## Clore Authentication Correction

The v4 public-sanitization release caught a `401` from Clore. The official
Clore API reference marks the `auth` header as mandatory for
`/v1/marketplace`; earlier unauthenticated captures had succeeded but were not
a durable contract. The connector now sends `CLORE_API_KEY`, and the default
hourly scope omits Clore when no key is configured. Existing Clore bronze,
silver, and gold observations remain immutable.

The release run still completed gold and publication with a warning:

```text
market-state-public-sanitize-20260725T1921
gold-market-state-public-sanitize-20260725T1921
```

Its public payload proved the sanitization fix: no `s3://` string or private
dashboard output root remained. Worker v5 and the final schedule release then
removed the unconfigured Clore source from the active scope; the final
production heartbeat completed successfully.

## Final Publication Verification

The implementation was published as:

```text
AdamSioud article commit       4190af4
Compute Bazaar pipeline commit 9147545
GitHub Pages run               30171769554
```

The Pages run completed successfully. The live article at
`https://www.adamsioud.com/exemplars/compute/feeling_the_compute.html` loaded
the production CloudFront state for
`gold-market-state-final-20260725T1928`: 46 current public rows and eight
aggregate occupancy-history rows. Serialized inspection found no `s3://`
value.

Public browser QA at 1280 x 720 and 390 x 844 confirmed:

- document width exactly matched the viewport at both breakpoints;
- the current Akash occupancy row rendered from live data;
- 16 current model-availability rows rendered separately;
- the history chart rendered eight data observations and its focus marker;
- the chart exposed a focusable `role=slider` control with a plain-language
  accessible label;
- no waiting/fallback state remained.

Final verification commands:

```text
uv run --with pytest pytest tests                  85 passed
focused article/Windmill/GPU tests                49 passed
Ruff blocking-error selection                     passed
JavaScript syntax (article and operator board)    passed
git diff --check (both repositories)              passed
```
