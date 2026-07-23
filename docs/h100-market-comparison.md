# H100 Market Checks

The public page shows the Compute Bazaar price from the latest hourly market run. We compare it
with other H100 price publishers to catch obvious mistakes, not to force all of the numbers to
match.

| Source | H100 price | Update basis | Checked |
| --- | ---: | --- | --- |
| [Compute Bazaar](https://d3n0n6h709c83f.cloudfront.net/featured-benchmarks.json) | latest hourly value | prices collected from marketplaces and official provider pages | hourly |
| [Ornn](https://ornn.com/) | $1.80-$1.90 | live traded spot prices | 24 Jul 2026 |
| [Silicon Data](https://www.silicondata.com/products/silicon-index) | $2.70 | daily neo-cloud price | 22 Jul 2026 |
| [Compute Desk](https://x.com/computedesk) | $2.42 | annual-rate snapshot shared on 17 Jun 2026 | 17 Jun 2026 |
| [Compute Index](https://www.computeindex.dev/) | $3.34 | lowest currently available H100 SXM price | 24 Jul 2026 |

These values are not like-for-like. A completed trade, an annual contract, the cheapest available
machine, and a balanced price across providers answer different questions. The useful check is
whether our result is explainable from its own source prices and sits in a plausible market range.

The next comparison step is a separate external-reference time series with source timestamps and
price bases. External index values must never be mixed into Compute Bazaar's provider inputs or
used to tune its output.
