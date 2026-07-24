# Sandbox Cost Integration Journal

Date: 24 July 2026

## Objective

Promote the completed sandbox-cost research package into the maintained Compute
Bazaar lake and the real AdamSioud Compute article. Preserve source provenance,
retain all comparable benchmark runs, add a defensible GPU comparison, and make
the result recur without pretending unstable price pages are automatic data
feeds.

## Source Audit

- Read the handoff `README.md` and `SOURCES.md` before implementation.
- Confirmed 33 hourly-price observations across 11 services.
- Confirmed the fixed 2026 cohort has eight unchanged members.
- Audited the public StarSling index, methodology, and matching run files at
  commit `c7c9abf328430e2b5a01b0a4f57863c0fdd87641`.
- Confirmed 38 service results from seven comparable public runs over five
  calendar days, 19-23 July 2026.
- Confirmed every accepted run uses 4 vCPU, 8 GB memory, and 40 GB disk.
- Confirmed earlier Better Auth runs used 2 vCPU and are incompatible.
- Verified the extraction against the public repository: all 38 canonical
  results reproduced; no source change was detected.
- Audited the project GPU history. The compatible H100 series uses
  `advertised_provider_floor_median_v1` and `advertised_hourly`.

## Decisions

1. The versioned evidence lives inside the Python package so builds and CI do
   not depend on ignored local CSV files.
2. Raw public benchmark files are captured under a commit-pinned bronze prefix.
3. Existing observations are immutable. A refreshed source that changes a known
   result fails rather than overwriting history.
4. Benchmark results keep exact timestamps and repeated intraday runs.
5. The same-job estimate uses only processor and memory because those are the
   comparable public rates in the current evidence.
6. The fixed hourly average keeps eight members through time.
7. The combined chart uses base 100, not one raw dollar axis.
8. Hourly Windmill builds publication data from reviewed evidence; a daily
   source check detects new benchmark runs. Provider price pages remain a
   reviewed input.
9. The article reuses the existing D3 and Safari CSS-zoom pointer conventions
   instead of introducing a chart framework.

## Discarded Approaches

- A raw GPU-price and sandbox-job-cost axis was rejected because the units and
  products are not comparable.
- “Volume” was rejected because no credible common transaction-volume source is
  present.
- A daily aggregate of the public benchmark was rejected because it would erase
  repeated intraday runs.
- Automatic scraping of all price pages was rejected because their billing
  semantics and markup are not stable enough to publish without review.
- A second standalone article was rejected. The benchmark belongs in the
  existing Tinkering narrative and maintained project pipeline.
- A new warehouse or chart library was rejected; DataFusion, Parquet, S3, and
  the article’s existing D3 approach are sufficient.

## Formulas

```text
hourly price =
  processor quantity * processor unit rate
  + memory GiB * memory GiB rate

runtime =
  sum(ten Better Auth published mean task times)

same-job estimated cost =
  runtime_seconds / 3600 * hourly price

base-100 value =
  current compatible value / first shared value * 100
```

## Commands Run

```sh
.venv/bin/sandbox-cost refresh-benchmark \
  --output-root /tmp/compute-bazaar-sandbox-refresh \
  --source-ref c7c9abf328430e2b5a01b0a4f57863c0fdd87641 \
  --check

.venv/bin/sandbox-cost build \
  --output-root data/sandbox-cost \
  --dashboard-output-root external/AdamSioud/exemplars/compute \
  --gpu-history-ref data/dashboard/compute-bazaar/benchmark-history.json

.venv/bin/python -m unittest \
  tests.test_sandbox_cost \
  tests.test_adamsioud -v

node --check external/AdamSioud/exemplars/compute/sandbox-cost.js

uv run python infra/windmill/bootstrap_market_schedule.py \
  --base-url http://127.0.0.1:18081 \
  --run-now \
  --wait \
  --run-id market-sandbox-release-20260724T190100
```

The deterministic build ID from the reviewed inputs is
`sandbox-cost-2d7942e7c6ef50cf`. The build identity includes the reviewed
evidence, compatible GPU rows, public GPU provenance, target shape, fixed
cohort, query hashes, and 12-decimal Gold precision rule.

## Data Caveats

- Four virtual processors are not metered identically by every service.
- Storage, network, plans, credits, retries, and work outside the ten tasks are
  excluded from estimated same-job cost.
- Observed dates are not silently relabeled as effective dates.
- A `between_observations` price point gives the first known later quote, not an
  invented exact change date.
- The H100/sandbox view compares relative movement only.
- H100 coverage expands from the early observations to the current feed, so the
  exploratory line is not a fixed-provider series.
- Seven matching benchmark runs are too short a history for broad performance
  claims.

## Frontend Integration

- Added one coherent sandbox sequence inside article point I, Tinkering.
- Added an hourly-price figure, separate runtime and estimated-cost figures,
  and a base-100 H100/sandbox figure.
- Added compact latest ledgers and collapsible complete tables.
- Source links are adjacent to the observations they support.
- Charts support pointer inspection, keyboard focus, screen-reader updates, and
  responsive resizing.

## Visual QA

- Desktop inspection used a 1280 x 720 viewport. All four D3 figures rendered,
  the 33-row hourly table and 38-row same-job table retained every observation,
  and the document had no horizontal overflow.
- Mobile inspection used a 390 x 844 viewport. Charts resized to the content
  column, wide ledgers remained inside their scroll wrappers, and the page
  width stayed within the viewport.
- Pointer inspection aligned with chart coordinates and stayed inside the
  viewport. Keyboard inspection with arrows, Home, and End updated the visible
  and screen-reader status text.
- The dense 883-point combined series renders as two lines without 1,766
  decorative point nodes; the underlying observations remain available to
  pointer and keyboard inspection.
- Source links resolve to public price pages or commit-pinned StarSling files.
  The article contains 92 source links and seven distinct benchmark runs.
- Browser console and network inspection found no article errors or warnings.
- The local page loaded the configured CloudFront object without falling back
  to the checked-in JSON. The fallback, S3 object, and CloudFront response were
  then made byte-identical.

## Deployment Record

- Final Windmill run: `market-sandbox-release-20260724T190100`.
- Schedule: `f/compute-bazaar/market_hourly_hourly`, enabled hourly in UTC with
  cron `0 0 * * * *`.
- Worker image digest:
  `sha256:2eab3d987cb53ad655f26af671f06860ecc1e94fbbd588fa27a15c66fbde6aaf`.
- The run produced 33 price observations, 38 same-job results, 10 fixed-average
  points, and 883 combined H100/sandbox observations.
- `gold`, `dashboard_export`, and `sandbox_cost` checks were `ok`. The overall
  market run remained `warning` because upstream provider-quality warnings are
  intentionally not hidden.
- Public artifact SHA-256:
  `dec19937d5dbda95dc22a828cf259bd027c662ef33f31b0fe9f0a86cda69c3d7`.
- Public data URL:
  `https://d3n0n6h709c83f.cloudfront.net/sandbox-cost.json`.
- A fresh local build from the final S3 GPU history produced the same build ID
  and byte-identical public JSON as the Linux worker.

## Next Refresh

1. Review a failed scheduled source check or run `sandbox-cost
   refresh-benchmark --check`.
2. Inspect commit-pinned bronze captures and upstream methodology changes.
3. Use `--update-evidence` only with the reviewed commit.
4. Review all public price pages and append observations without rewriting
   history.
5. Validate, build, run focused and full tests, then inspect the article.
6. Let the next hourly Windmill heartbeat publish `sandbox-cost.json`.
