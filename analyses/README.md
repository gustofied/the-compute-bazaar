# Market Models and Views

Each market model has two linked parts:

- `models/` contains reusable, read-only DataFusion SQL.
- `blueprints/` contains Perspective layouts; several blueprints may reference one model.

The model decides which rows and columns exist. The blueprint decides how that result
is viewed. Neither copies market data out of the lake.

```bash
compute-bazaar model list
compute-bazaar model run h200-under-4
compute-bazaar blueprint open h200-under-4
```

The Terminal **Save** action writes both files. Agents can write them separately:

```bash
compute-bazaar model save my-model --file query.sql
compute-bazaar blueprint save my-chart --model my-model --config chart.json
```

These are saved queries and views, not materialized Gold tables. Promote a model into
the pipeline's Gold SQL only when its schema and meaning should become a shared contract.
