# Observed Advertised GPU-Hour Benchmark

The Compute Bazaar frontier benchmark is an observed advertised-price product. It is not yet a
transaction index, settlement index, or annual-contract index.

The benchmark deliberately distinguishes three things:

- an advertised quote: a public or API-observed asking price
- availability: evidence that an offer could be requested or rented when observed
- an executed transaction: a price at which a buyer and seller actually traded

The current product has the first two evidence types. It does not have a licensed transaction tape,
so it must not be described as volume-weighted or utilization-weighted.

## Scope

The benchmark covers four GPU families:

- H100
- H200
- B200
- B300

Inputs come from two evidence classes:

- live marketplace inventory fetched from provider APIs
- curated observations from official provider pricing pages

Every price is normalized to USD per GPU-hour before calculation. Multi-GPU instances are divided
by their GPU count.

## Eligible Observations

The benchmark accepts:

- `available`: a live provider offer
- `published_rate`: a current official advertised rate
- `published_rate_request`: a current advertised rate that requires a sales or capacity request

It excludes:

- unavailable live offers
- GPU component rates that exclude required CPU, RAM, or storage
- announced future prices
- reserved or committed-term prices
- zero or negative prices

Reserved, future, and unavailable rows remain in the evidence layers and benchmark-constituent
table for research; they do not enter this advertised-hourly benchmark.

## Calculation

For each GPU family:

1. Select eligible normalized observations.
2. Find the lowest eligible price from each provider.
3. Use those provider floors as benchmark constituents.
4. Publish the median of provider floors as the benchmark value.

This prevents a marketplace with many listings from receiving more index weight merely because it
returned more rows. The median also reduces the effect of one unusually cheap or expensive
provider.

The output retains separate descriptive fields:

- `benchmark_usd_gpu_hr`: median of provider floors
- `provider_floor_mean_usd_gpu_hr`: mean of provider floors
- `provider_floor_p25_usd_gpu_hr` and `provider_floor_p75_usd_gpu_hr`: interquartile range of
  provider floors
- `floor_usd_gpu_hr`: cheapest eligible observation across all providers
- `median_usd_gpu_hr`: median across all eligible observations
- `simple_mean_usd_gpu_hr`: mean across all eligible observations
- `p25_usd_gpu_hr` and `p75_usd_gpu_hr`: distribution across all eligible observations

`fact_benchmark_constituents` marks one included floor per provider. Higher observations from the
same provider remain auditable with `exclusion_reason = higher_same_provider_offer`. Future and
committed-term observations use `future_rate` and `committed_term_rate`.

## Current Limits

Version 1 is a family-level advertised-price benchmark. It currently pools PCIe, SXM, HGX, and
NVLink offers within a GPU family and does not yet standardize region, minimum term, networking,
storage, support level, taxes, or service-level guarantees. A later institutional methodology can
publish narrower sub-indices once coverage supports them.

## Evidence And Freshness

Live API rows use the provider fetch time. Curated rate-card rows use the time the official source
was checked, not the time the same observation happened to be re-ingested. The structured bronze
record includes the source URL, checked time, source version, price basis, and access mode.

Rate-card observations are context for price discovery, not proof that a machine can be rented at
that instant. Procurement must confirm availability through a live provider API or sales workflow.

The evidence hierarchy for future versions is:

1. verified executed transactions, when their terms and rights permit benchmark use
2. live executable or reservable offers
3. observed marketplace asks with availability metadata
4. current official rate cards
5. manually reviewed secondary evidence, used only when the original source is unavailable

Higher-ranked evidence does not silently replace lower-ranked evidence. Every observation retains
its basis so separate quote, availability, and transaction products can be calculated.

## Historical Comparability

The current H100 history is broader than the history suitable for the public sandbox comparison.
The lake retains both:

- `gpu_h100_daily_coverage`: every retained day, including low-coverage observations
- `gpu_h100_eligible_history`: hourly H100 prints with at least 10 distinct contributing providers

As audited on 24 July 2026, the retained H100 series contains 887 prints over 37 calendar days, but
only 30 hourly prints on 23-24 July meet the 10-provider publication gate. The sandbox common-start
chart therefore begins at the first eligible hourly print; it does not draw a continuous line
through earlier one-provider observations.

The 10-provider gate is a transparent research and publication threshold, not a claim that the
result is settlement-grade. Excluded history remains queryable so coverage changes can be inspected
and the threshold can be revised through a new methodology version rather than hidden.

## Relationship To Other Indices

This benchmark measures advertised hourly asks. It should not be tuned to reproduce another
publisher's number.

[Ornn](https://data.ornn.com/faq) describes its index as transaction-based and volume-weighted.
[Silicon Data](https://www.silicondata.com/products/silicon-index) combines broader provider and
private-market coverage with its own standardization and validation.
[Compute Index](https://www.computeindex.dev/) publishes lowest advertised prices and reports
availability separately. Annual or committed-price series also measure a different contract basis.
Those products are useful external checks, but they are not constituents in the Compute Bazaar
calculation.

The design is informed by the IOSCO benchmark principles on data sufficiency, hierarchy,
methodology, and transparency, but Compute Bazaar does not claim IOSCO compliance. Median and
interquartile-range summaries follow standard robust descriptive practice; they do not turn
advertised quotes into transactions.

The methodology version is:

```text
advertised_provider_floor_median_v1
```

The calculation is authored as DataFusion SQL in
`src/the_compute_bazaar/prices/benchmark_queries.py` and materialized into:

- `gold.fact_benchmark_values`
- `gold.fact_benchmark_constituents`
