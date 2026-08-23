# Architecture

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="../assets/compute-bazaar-architecture-dark.png">
    <img src="../assets/compute-bazaar-architecture.png" alt="The Compute Bazaar architecture" width="100%">
  </picture>
</p>

## Data

The lake follows the medallion pattern:

- **Bronze** is raw source data.
- **Silver** is sanitized and normalized market data.
- **Gold** is opinionated, analysis-ready data: indexes, availability histories,
  and other market models.

Each layer can be rebuilt from the one before it without losing the raw record.

The pipeline runs locally or hourly with Windmill. See [Pipeline](../infra/windmill/README.md).

The public lake is a checksummed Silver and Gold snapshot published through a
rolling GitHub Release or S3 with CloudFront. See
[Public lake](../infra/aws/public-feed/README.md).

## Query layer

DataFusion opens the selected lake:

| Selection | Contains |
| --- | --- |
| Public (default) | Synced Silver and Gold data |
| Local | Silver and Gold from a local refresh |
| Market | Fresh local offers in `silver.gpu_offers` |

A compatible lake can be selected with `--lake-root` or
`COMPUTE_BAZAAR_LAKE_ROOT`, so the same query layer and Terminal can run over
your own data.

The public lake contains only sanitized Silver and Gold data. When opened
locally, the Public and Local catalogs are joined with the private operational
ledger. Direct reads and preflights appear in `silver.offer_observations`;
Fleet remains under `fleet.*`.

Queries are read-only and returned as Apache Arrow. The CLI prints the result;
the Terminal passes it to Perspective. SQL models and Perspective views are
saved separately.

## Fleet

<p align="center">
  <img src="../assets/compute-bazaar-fleet-flow.svg" alt="A live offer or SSH host entering Fleet" width="100%">
</p>

Preflight checks the offer again before spending. A successful launch creates
an Allocation and registers the machine in Fleet.

An existing rented GPU cluster can also be attached through an OpenSSH host.
Fleet then records its hardware, health, telemetry, and workloads.

## CLI and Terminal

The CLI and Terminal use the same services. The CLI returns tables or JSON; the
Terminal presents Data, Fleet, Eval, and Trade through a Tauri window backed by
a local FastAPI process. Agents connect through ACP and use the same CLI.
