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
| GridStackHub | Public external multi-provider reference feed | No capacity claim; excluded from benchmark constituents |
| Cloud GPU Prices | Public external catalog with source evidence and explicit price comparability | No capacity claim; excluded from benchmark constituents |
| Thunder Compute | Public current prices plus configuration availability | One currently available bundle; unavailable prices remain evidence only |
| Vultr | Public GPU plans plus regional plan deployability | One deployable bundle per available region; unlocated prices remain evidence only |
| Scaleway | Public per-zone instance prices and stock status | One deployable bundle per `available` or `scarce` type; `shortage` remains evidence only |
| Oracle Cloud | Public GPU pay-as-you-go price-list API | Current published rate only; no capacity claim |
| OVHcloud | Public hourly GPU instance catalog | Current published rate only; no capacity claim |
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

Scaleway documents public instance-type prices and a separate per-zone
availability endpoint. Euro prices are converted with the latest ECB EUR/USD
reference rate; both the provider price and FX observation remain in raw
evidence and row metadata:
<https://www.scaleway.com/en/developers/api/instance/instance-types>.

Oracle documents its public product price-list API and the `partNumber` and
`currencyCode` filters. The connector reads only Compute GPU SKUs measured in
GPU-hours; NVIDIA AI Enterprise license SKUs are deliberately excluded:
<https://docs.oracle.com/en-us/iaas/Content/Billing/Tasks/signingup_topic-Estimating_Costs.htm>.

OVHcloud's public order catalog exposes hourly Public Cloud GPU VM plans and
machine metadata. The connector retains only Linux GPU instance consumption
plans, converts the French catalog's EUR prices with the same ECB observation,
and does not infer stock from catalog presence:
<https://eu.api.ovh.com/console-preview/?section=%2Forder&branch=v1#get-/order/catalog/public/cloud>.

GridStackHub is collected as a comparison and provider-discovery source. Its
upstream seller, original source timestamp, collection method, and source URL
are preserved, but every row is marked `external_reference`. This prevents
aggregated AWS, Lambda, RunPod, Vast, and other rows from becoming duplicate
benchmark votes:
<https://gridstackhub.ai/developers>.

Cloud GPU Prices exposes a documented, paginated JSON catalog. All frontier
offerings land in bronze; only variants explicitly marked as fixed-GPU,
complete, comparable totals become silver rows. Provider, product category,
pricing structure, verification time, and source URL are retained. Every row
remains `external_reference`:
<https://cloudgpuprices.com/agents>.

GetDeploying is an optional authenticated comparison feed focused on the four
frontier benchmark families. It remains `external_reference` even when its
source status says available, because the same underlying seller may already
arrive through a direct connector:
<https://getdeploying.com/help/api>.

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
| GetDeploying | `GETDEPLOYING_API_KEY` | Paginated external frontier-GPU offerings across provider catalogs |
| JarvisLabs | `JL_API_KEY` | Current on-demand/spot prices and provider-reported free devices |
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

## Source Expansion

The source universe is larger than the default heartbeat. We maintain a
classified source registry in [provider-registry.md](provider-registry.md).
Direct APIs are preferred for benchmark constituents. Cross-cloud aggregators
must retain the upstream seller in `provider` and their own identity in
`source_connector`. External indexes are validation surfaces, not provider
constituents, because importing them would duplicate their underlying sellers
and make the benchmark circular.
