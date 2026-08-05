# Providers

Every provider follows one path:

```text
API response -> raw Bronze capture -> GpuOffer Silver rows -> DataFusion Gold
```

To add a source:

1. Add one module here with a client and a normalizer returning `GpuOffer` rows.
2. Add its ingestion function to `prices/pipeline.py`; persistence, manifests, and
   Kafka publication stay in `_persist_publish_snapshot()`.
3. Register it once in `prices/provider_registry.py` with its source kind,
   observation kind, credentials, and any default fetch options.
4. Add a hermetic normalization example to `tests/test_core.py`.

The hourly runner and Windmill schedule must not contain provider-specific
branches. Credentials are passed to Windmill as one secret JSON map assembled
from the registry.

Silver rows must identify the provider and source offer, observation time, raw
GPU name, canonical GPU model, GPU count, hourly USD price, availability, price
basis, and raw evidence reference. Marketplace asks, cloud rates, spot prices,
and aggregator references may coexist; `source_connector`, `source_kind`, and
`observation_kind` are retained in Gold so a query or benchmark can select the
intended cohort without confusing an aggregator with the upstream provider.
