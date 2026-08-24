# Market Models and Views

The Bazaar includes reusable ways to query and display market data:

- `models/` contains read-only DataFusion SQL. A model decides which rows and columns to return.
- `blueprints/` contains Perspective layouts. A blueprint decides how to display the result, and several can use the same model.

Both work directly from the lake without copying the underlying market data.

```bash
compute-bazaar model list
compute-bazaar model run h200-under-4
compute-bazaar blueprint open h200-under-4
```

These examples ship with the Terminal. Your own models and views are saved in the local
Compute Bazaar state directory, not in this folder:

```bash
compute-bazaar model save my-model --file query.sql
compute-bazaar blueprint save my-chart --model my-model --config chart.json
```

Set `COMPUTE_BAZAAR_ANALYSIS_ROOT` to use another location. A saved model is a query,
not a materialized Gold table. Move it into the pipeline's Gold SQL only when it should
become a stable, shared part of the data model.
