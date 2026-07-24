# GPU Market Source Registry

This registry separates sources by what they can actually prove. A provider
logo is not automatically a live offer, and an aggregator row is not an
independent seller.

## Integrated Sources

| Source | Role | Ingestion | Benchmark use |
| --- | --- | --- | --- |
| Vast.ai | Marketplace | Live authenticated API | Eligible live seller offers |
| Lium | Marketplace | Live authenticated API | Eligible live seller offers |
| Clore.ai | Marketplace | Public live API | Eligible live seller offers |
| Akash | Marketplace | Public live price/capacity summary | Eligible live seller summary |
| RunPod | GPU cloud | Public current catalog/stock | Eligible when currently available |
| Verda | GPU cloud | Public catalog; OAuth live regions | Catalog price or eligible live region |
| Thunder Compute | GPU cloud | Public price and availability APIs | Eligible only while marked available |
| Vultr | Cloud | Public plans and regional deployability | Eligible only with a deployable region |
| Scaleway | Cloud | Public zone prices and stock-status API | Eligible while `available` or `scarce`; `shortage` is evidence only |
| Oracle Cloud | Hyperscaler | Public pay-as-you-go GPU price-list API | Published rate only; no capacity claim |
| OVHcloud | Cloud | Public hourly GPU instance catalog API | Published rate only; no capacity claim |
| AWS | Hyperscaler | Current EC2 Spot API | Price observation, no capacity claim |
| Azure | Hyperscaler | Public retail prices API | Price observation, no capacity claim |
| Spheron | Multi-provider marketplace | Public live offer feed | Upstream seller is the provider |
| Inference.sh | Cross-cloud catalog | Public hourly cached catalog | Upstream seller is the provider |
| GridStackHub | Cross-cloud price aggregator | Public daily API | External reference only; upstream seller retained |
| Cloud GPU Prices | Cross-cloud VM/serverless catalog | Public documented JSON API | External reference only; complete comparable totals normalized |
| Prime Intellect | Multi-provider marketplace | Optional authenticated API | Upstream seller is the provider |
| Shadeform | Cross-cloud control plane | Optional authenticated API | Upstream seller is the provider |
| Sesterce | GPU cloud/aggregator | Optional authenticated API | Eligible live offers |
| TensorDock | Marketplace | Optional authenticated API | Capacity evidence; component rates excluded |
| Hyperstack | GPU cloud | Optional authenticated API | Eligible live stock and prices |
| Lambda Cloud | GPU cloud | Optional authenticated API | Eligible capacity regions and prices |
| DigitalOcean | Cloud | Optional authenticated API | Eligible launchable regions and prices |
| GPUs.io | Price aggregator | Optional authenticated API | Upstream seller is the provider |
| GetDeploying | Cross-cloud price aggregator | Optional authenticated daily API | External reference only; upstream seller retained |
| JarvisLabs | GPU cloud | Optional authenticated API | Eligible free-device prices |

The official rate-card feed adds advertised observations from Civo, Crusoe,
Denvr, DigitalOcean, GMI Cloud, Hyperbolic, Hyperstack, Koyeb, Lambda, Massed
Compute, Nebius, RunPod, TensorDock, Verda, VESSL, and Voltage Park. Rate-card
rows are price evidence, not proof of immediate capacity.

## Next Direct Connectors

These are sensible next accounts or API investigations. They are not active
sources until their response shape, pricing basis, availability semantics, and
terms have been verified.

| Source | Useful official surface | Required work |
| --- | --- | --- |
| Hyperbolic | Marketplace VM and bare-metal option APIs | API token; verify option-level availability |
| Shape | Curated multi-provider marketplace and session API | API key; confirm a read-only offer/quote endpoint before using session prices |
| SaladCloud | GPU class catalog and organization availability API | Organization and read-only API key |
| Civo | Sizes and regions APIs | API key; join account-visible GPU sizes to published rates |
| Koyeb | Platform API and GPU instance catalog | API token; verify region-level deployability |
| Crusoe Cloud | VM types and capacity APIs | Project-scoped read credential; join pricebook |
| CoreWeave | GPU catalog, zones, and capacity plans | Confirm a read-only capacity/price surface |
| Nebius | Compute catalog, pricing, and reservations | Service account; map regions and SKUs |
| Google Cloud | Cloud Billing Catalog and Compute APIs | Billing catalog key/service account; map accelerator SKUs |
| Genesis Cloud | Compute API | Account token; validate current instance availability |
| DataCrunch | Cloud API | Read token; validate dynamic and fixed price modes |
| Latitude.sh | Compute API | Read token; identify accelerator SKUs and stock |
| Novita AI | GPU instance API | Read token; validate instance-level prices and capacity |
| Cudo Compute | Compute API and marketplace catalog | Read token; verify whether catalog rows prove current capacity |
| Paperspace | Machines API | API key; join machine types, regions, and current availability |
| IBM Cloud | Global Catalog and VPC APIs | Service ID; map GPU profiles to regional public prices |
| Seeweb | Server API and public catalog | API token; verify GPU stock and hourly price semantics |
| Yotta | GPU cloud catalog | Confirm a supported read-only catalog endpoint |
| Mithril | GPU cloud catalog | Confirm a supported read-only catalog endpoint |
| Gcore | Cloud API and GPU flavors | API token; map flavors, regions, and public pricing |
| Akamai Cloud | Cloud Manager API | API token; identify GPU plans and deployable regions |
| Nscale | GPU cloud catalog | Confirm a machine-readable price and availability feed |
| IO.net | Explorer and cloud APIs | Obtain supported service authentication; browser JWTs are not suitable for hourly production |
| Lightning AI | Multi-cloud GPU marketplace | Confirm a read-only marketplace catalog endpoint |
| TensorWave | Cloud API | Confirm self-serve catalog and availability endpoints |
| Fluidstack | Capacity catalog | Confirm whether a machine-readable, non-sales feed exists |

## External Validation Feeds

Ornn, Silicon Data, Compute Desk, Compute Index, GPU Rental Rate Index,
GPUCloudCompare, ComputePrices, and Cloud GPU Prices can help
compare our output with other market views. They should be stored as external
benchmark observations, not mixed into `fact_gpu_listings`: many already
contain AWS, Lambda, RunPod, Vast, and other sellers that Compute Bazaar
observes directly.

SkyPilot's open service catalog and GPU Compass are especially useful discovery
and validation surfaces: the catalog currently covers 24 providers and refreshes
roughly every seven hours. Before republishing its rows through the public
Compute Bazaar feed, confirm the catalog data's redistribution terms. The
ComputePrices API is not an ingestion candidate under its current terms because
they prohibit using the feed to operate a competing GPU-price comparison
service.

## Admission Rule

A new source enters the hourly benchmark path only after we can answer:

1. Who is the actual seller?
2. Is the number on-demand, spot, reserved, negotiated, or a starting rate?
3. Does the response prove current deployability, a stock count, or price only?
4. What timestamp and raw response support the row?
5. Can repeated rows be deduplicated across connectors?

Until then, the data can still land in bronze for research without silently
becoming benchmark truth. GridStackHub, Cloud GPU Prices, and GetDeploying
follow this path through `external_reference` silver rows.
