# Market

`market` is the new provider-by-provider path for live GPU offers. It is built
beside the broad pipeline so the historical lake stays intact while sources
move over one at a time.

```text
source API -> Bronze JSON -> Silver gpu_offers -> market generation
                                      |
                                      +-> preflight -> allocation -> Fleet
```

Bronze stores the source response. Silver maps each offer to the small
`GpuOffer` contract. A market generation combines one completed run from each
source and exposes `silver.gpu_offers` through DataFusion.

Sesterce is the first source. Before spending, The Bazaar reads Sesterce again
and checks the selected offer. A successful launch becomes an Allocation and a
Fleet node.

```bash
export SESTERCE_API_KEY=...
compute-bazaar market ingest sesterce
compute-bazaar terminal market
```

The [broad provider pipeline](../prices/providers/README.md) continues to build
the historical Silver and Gold lake while sources move to this path.
