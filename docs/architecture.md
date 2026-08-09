# Architecture

```text
providers -> Windmill -> AutoMQ -> S3 -> DataFusion -> CLI / Terminal
```

## Market data

Windmill runs provider ingestion each hour. AutoMQ carries the live observations
as a Kafka-compatible stream. S3 keeps the durable lake:

```text
Bronze  raw provider evidence
Silver  normalized market data
Gold    shared market models
```

A sanitized Silver and Gold copy is published as the public lake. The CLI syncs
that Parquet data locally, so DataFusion can query it without cloud credentials
or a database server.

## Query layer

DataFusion runs SQL over the lake and returns Apache Arrow data. The CLI prints
the result directly; the Terminal passes the same Arrow result to Perspective
for interactive tables and charts.

## Market models

A market model is a reusable way of reading the compute market:

```text
market lake -> DataFusion SQL model -> Arrow result -> Perspective view
```

The SQL is the model logic. The view decides how its result is displayed. An
index, benchmark, curve, signal, or monitor is something the model may produce.

This also fits agents. An agent can run or write a model without opening the
Terminal, save it for later, or leave a view for a person or another agent to
use as new market data arrives.

The model and view remain separate, following
[Rerun's blueprint idea](https://rerun.io/docs/concepts/visualization/blueprints).
A working model becomes Gold only when it should be a shared data contract.

## Interfaces

The CLI and Terminal use the same DataFusion engine. Data is available now,
Eval contains the Harbor evaluation viewer, and Trade remains reserved for the
later execution system.
