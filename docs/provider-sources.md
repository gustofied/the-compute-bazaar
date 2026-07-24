# Provider Sources

The source connector and the seller are separate concepts.

- `provider` is the cloud or marketplace selling the compute.
- `source_connector` is the API through which Compute Bazaar observed it.

Direct connectors normally have the same value for both. Cross-cloud catalogs
such as Spheron, Inference.sh, Shadeform, and GPUs.io retain the upstream seller
as `provider`. Gold benchmark floors are deduplicated at the seller level.

## Default Hourly Sources

| Connector | Evidence | Capacity meaning |
| --- | --- | --- |
| Vast | Direct live marketplace offers | GPUs in each rentable machine bundle |
| Lium | Direct live executor API | Provider-reported available GPUs |
| Spheron | Public multi-provider live offers | Provider units when supplied, otherwise one bundle |
| Inference.sh | Public cross-cloud available catalog, cached for one hour | One deployable bundle per available region |
| Clore | Direct public live marketplace | Available server or partial-rental GPUs |
| Akash | Public live price and availability summary | Provider-reported available GPU units |
| RunPod | Public current GPU-type price and stock status | One-GPU lower bound, not exact stock |
| Verda | Public catalog; live stock only with OAuth credentials | One bundle per available location when authenticated |
| AWS Spot | Current spot-price observations | No capacity claim |
| Azure Retail | Current public retail-price observations | No capacity claim |
| Published rate cards | Curated official advertised prices | No capacity claim |

Inference.sh documents `GET /instances/types` as a no-auth catalog backed by
Shadeform, with per-region availability and a one-hour public cache:
<https://inference.sh/docs/api/rest/instances>.

## Optional Authenticated Sources

The hourly provider scope expands automatically when a credential exists:

| Connector | Environment variable | Evidence |
| --- | --- | --- |
| Prime Intellect | `PRIME_INTELLECT_API_KEY` | Live multi-cloud availability |
| Shadeform | `SHADEFORM_API_KEY` | Live multi-cloud instance inventory |
| Sesterce | `SESTERCE_API_KEY` | Live GPU Cloud offers |
| TensorDock | `TENSORDOCK_API_KEY` | Live hostnode stock and GPU component rates |
| Hyperstack | `HYPERSTACK_API_KEY` | Real-time stock joined to its current pricebook |
| Lambda Cloud | `LAMBDA_CLOUD_API_KEY` | Current instance types and capacity regions |
| DigitalOcean | `DIGITALOCEAN_API_TOKEN` | Current GPU Droplet sizes and launchable regions |
| GPUs.io | `GPUS_IO_API_KEY` | Cursor-paginated current multi-provider prices |
| Verda | `VERDA_CLIENT_ID`, `VERDA_CLIENT_SECRET` | Live location-level availability |

TensorDock GPU-only rates are written to bronze/silver and count as capacity
evidence, but they are excluded from the benchmark until a complete executable
instance cost can be constructed.

GPUs.io documents one current row per provider/configuration, explicit
availability, region lists, total and per-GPU price, and cursor pagination:
<https://gpus.io/docs/prices>.

## Coverage Targets

`gpu-prices frontier-coverage` reports three different measures for H100,
H200, B200, and B300:

1. live offer rows
2. conservative live GPU capacity lower bound
3. current price observations

These are not interchangeable. Fifty GPUs can be one 50-GPU stock pool, fifty
single-GPU listings, or fifty observations over sources and price types.
Compute Bazaar reports each separately and never clones an inventory row merely
to reach a target.
