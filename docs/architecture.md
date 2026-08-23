# Architecture

The Bazaar separates market history, live selection, private operations, and
agent evaluation. The CLI and Terminal are the common interface.

```text
market sources -> market record -> DataFusion -> CLI / Perspective
live source read -> preflight -> allocation -> Fleet -> workloads

Harbor -> tasks -> jobs / trials -> Eval
ACP agent -----------------------> CLI / Terminal
market models - - - - - - - - --> Trade
```

Trade is not yet implemented.

## State

| State | Contains | Storage | Exposure |
| --- | --- | --- | --- |
| Market history | Source responses, normalized observations, shared models | JSON and Parquet, locally or in S3 | Sanitized Silver and Gold can be public |
| Live market | Source runs and selectable GPU offers | Local JSON and Parquet | Private |
| Operations | Direct reads, preflights, provisioning, allocations, Fleet, telemetry, workloads | SQLite and local files | Private |
| Eval | Harbor tasks, jobs, trials, and reports | Repository tasks and job artifacts | Private unless published |

## Market record

```text
source cycle -> Bronze -> Silver -> Gold
```

- **Bronze** preserves the source response and request metadata.
- **Silver** normalizes observations into a shared market contract.
- **Gold** contains reusable models and retained histories.

The same source cycle runs locally or on a Windmill schedule. See the
[Pipeline](../infra/windmill/README.md) for its jobs and deployment.

The public lake is a checksummed, sanitized Silver and Gold snapshot. It is
published through a rolling GitHub Release and can also be served from S3
through CloudFront. See [Public lake](../infra/aws/public-feed/README.md).

## Selection and Fleet

Recorded history describes the market. Selection needs a fresh provider read
and the exact native fields required to buy one offer.

```text
offer -> preflight -> request -> allocation -> Fleet node
OpenSSH target -> attach --------------------> Fleet node

Fleet node -> inspect -> doctor -> monitor -> workload
```

Preflight repeats the provider check immediately before a paid request. The
request carries a price ceiling, runtime budget, and explicit confirmation. A
successful provider response becomes an Allocation; the resulting machine is
then registered in Fleet.

An existing NVIDIA machine can enter Fleet through an OpenSSH target without
an Allocation. OpenSSH owns host resolution, keys, agents, and jump hosts.
Fleet stores the target, expected hardware, inspections, telemetry, and
workload state locally.

## Catalogs

The CLI can open three DataFusion catalogs.

| Selection | DataFusion catalog |
| --- | --- |
| Default | Synced public Silver and Gold, plus private operational views |
| Local | Locally refreshed Silver and Gold, plus private operational views |
| Market | Source-first local offers in `silver.gpu_offers` |

The default and local catalogs expose scheduled observations in
`silver.offer_observations`. Direct reads and preflights from the operational
ledger are added to that view with their purpose intact. Fleet tables remain
private under `fleet.*`.

DataFusion executes bounded, read-only SQL and returns Apache Arrow data. The
CLI prints it directly; Perspective receives the same Arrow result in the
Terminal. Saved SQL models and Perspective views remain separate files.

## Interfaces

The CLI is the command interface for people, scripts, and agents. It prints
tables for people and JSON when another program needs structured output.

The Terminal runs a local FastAPI backend inside a Tauri window, with a browser
fallback. Its Data workspace uses DataFusion and Perspective; Fleet uses the
private operations services; Eval reads Harbor reports.

The Agent drawer connects an external agent through ACP. The agent works in the
repository and uses the same `compute-bazaar` CLI.

Eval remains a Harbor system for tasks, jobs, trials, and reports. Trade is a
future workspace for instruments built from market models; it is not an
execution venue today.

## Invariants

- Bronze keeps source evidence; normalization begins in Silver.
- Every Silver row retains source lineage; public copies remove private refs.
- Gold is derived from declared Silver inputs and carries a run manifest.
- Paid provisioning requires a fresh preflight, a cost bound, and confirmation.
- Fleet identity, SSH details, telemetry, and workload logs remain private.
- Public sync verifies checksums before replacing the local cache.
- Agents use the same commands and contracts as people.
