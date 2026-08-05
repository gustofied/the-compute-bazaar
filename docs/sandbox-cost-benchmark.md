# Measured Workload Cost

The active sandbox product estimates what one pinned software workload cost to
run across compatible sandbox services. Runtime comes from the
[StarSling HPC Sandbox Benchmark](https://github.com/starslingdev/hpc-sandbox-benchmarks).
Processor and memory prices come from the public source linked for each service.

This is not a live sandbox-price index. It is a measured workload-cost
comparison.

## Economic Measure

For each completed benchmark job:

```text
estimated job cost = measured runtime seconds / 3600 * applicable hourly rate
```

The headline is the median estimated job cost across the latest compatible
StarSling run. The chart retains every comparable job and shows each service's
median and p25-p75 cost range.

The estimate covers processor and memory only. It excludes startup, teardown,
retries, storage, network transfer, control-plane fees, minimum billing periods,
discounts, and taxes. It is descriptive rather than an invoice or executed
price.

## Measurement Contract

The current comparable shape is four processors, 8 GiB of memory, and 40 GB of
disk. Each result must contain the ten selected Better Auth task phases and the
same StarSling methodology generation. Incompatible shapes and incomplete jobs
are rejected from the latest comparison rather than silently mixed in.

Runtime remains in Gold as an audit field because it is the denominator of the
cost formula. It is not a separate public product.

## Data Path

Bronze retains retrieved StarSling source files and source references with
checksums. Silver contains normalized jobs, phases, machine shapes, source run
identifiers, timing precision, and the price input selected for each service.
Gold contains individual estimated job costs, service distributions, compatible
run history, and the latest publication model.

The active price inputs live in:

```text
src/the_compute_bazaar/sandbox_cost/evidence/workload-cost-inputs.json
```

They exist only to calculate workload cost. Each row preserves the public price
URL, observed date, billing unit, machine-shape assumptions, and normalized
hourly amount.

The previous 33-observation sandbox-price research is archived at:

```text
archive/sandbox-prices/hourly-price-observations.json
```

Those observations are sparse manual quotes. They are not an hourly market feed
and do not power active charts or publications.

## Public Contract

The public data endpoint is:

```text
sandbox/workload.json
```

It identifies StarSling by name and URL, includes the source benchmark runs and
the service price-source links, and exposes only the workload-cost publication.
The retired `sandbox/rates.json` and `sandbox/relative.json` views are not built
or published.

## Refresh Cadence

The repository checks the StarSling source daily. A new measured observation is
created only when StarSling publishes a new compatible run. StarSling runs are
manually initiated upstream, so the measurement series is irregular rather than
hourly or weekly by contract.

Price inputs require a reviewed update when a provider changes its public
billing model or rate. A source-page change is not automatically accepted as a
new normalized price.

## Commands

Validate canonical evidence:

```bash
uv run sandbox-cost validate
```

Check upstream StarSling evidence without changing the canonical dataset:

```bash
uv run sandbox-cost refresh-benchmark --check
```

After reviewing a compatible upstream change:

```bash
uv run sandbox-cost refresh-benchmark --update-evidence --publish-operational
```

Build Bronze, Silver, Gold, and the public workload snapshot:

```bash
uv run sandbox-cost build \
  --output-root data/sandbox-cost \
  --dashboard-output-root data/dashboard/compute-bazaar
```

## Maintenance Rules

- Preserve every source URL, retrieval timestamp, checksum, run SHA, and price
  date used by a published cost.
- Never label a billing unit as an observation cadence.
- Never connect runs across incompatible StarSling methodology generations as
  one performance trend.
- Never replace a historical price input silently; append or review the change.
- Keep runtime available for audit while presenting cost as the economic output.
