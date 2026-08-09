# compute-bazaar-bench

A benchmark for agents working in compute markets.

> hey, i mix eval/evaluation/task/env, they are the same thing btw

The benchmark brings together two complementary styles of environments:

### Harvey-Style Professional Work

Using [Harvey's Legal Agent Benchmark](https://www.harvey.ai/blog/introducing-harveys-legal-agent-benchmark) gives this family of evaluations methodological grounding. Instead of inventing benchmark tasks from scratch, we start with task forms that already represent real professional work and test whether they transfer meaningfully into compute transactions.

The deals and commentary from [Epilogue](https://epilogue.inc/) and
[ComputeDesk](https://www.compute-desk.com/) around compute desks and deal flow
motivate the work here, especially their interest in involving agents.

[**transactions**](evals/transactions/README.md) evaluates professional work
that moves an OTC or reserved-compute transaction from initial intent toward
executable paper.

### Game-Like Environments

Game-like environments place agents inside changing compute-market processes,
including compute procurement, brokerage, matching, and negotiation. They are
more alive and interactive than closed professional-work evaluations, and their
stateful structure makes them more adaptable for training.
The first implemented environment is
[`reliability-is-blind`](evals/reliability-is-blind/README.md).

## Setup

For the most part, the benchmark follows Harbor's task and evaluation
methodology.

```text
compute-bazaar-bench/
|-- dataset.toml
|-- evals/
|   |-- reliability-is-blind/
|   `-- transactions/
|-- viewer/
`-- jobs/
    |-- raw/
    `-- reports/
```

Open the terminal:

```bash
uv sync --extra terminal
pnpm --dir terminal install
source .venv/bin/activate
compute-bazaar data sync
compute-bazaar terminal
```

## Evaluations

### [transactions](evals/transactions/README.md)

Its first three planned tasks move through intake, diligence, and contracting:

```text
messy intent -> organized evidence process -> controlled transaction paper
analyze      -> draft                      -> review
```

> Can an agent perform the professional work required to advance a compute
> transaction accurately, with evidence, and without losing the deal's
> controlling terms?

### [reliability-is-blind](evals/reliability-is-blind/README.md)

`reliability-is-blind` is the existing interactive brokerage evaluation. An
agent places supply into deals and must learn which suppliers to trust from
delivery outcomes without receiving hidden causal labels.

## Method

The initial tasks will be explicit compute-market adaptations of Harvey LAB
tasks. Each adaptation should preserve the upstream task's professional shape
while replacing its matter with original compute-specific evidence and risks:

- a closed synthetic matter;
- a short delegated instruction;
- a reviewable professional deliverable;
- planted issues and conflicting evidence;
- a source-grounded rubric with discrete criteria; and
- Harbor evaluation with transparent provenance.

The upstream repository, commit, task path, Harbor conversion, adaptation
notes, matter digest, and rubric digest should be recorded for every task.

## Beyond Transactions

The broader benchmark can eventually cover market intelligence, hedging,
financing, infrastructure development, and market operations. Interactive or
game-style environments may later test behavior, privacy, communication, and
negotiation across a changing deal state.

Harvey's current contracting benchmark similarly freezes negotiations at
discrete points before pursuing interactive negotiation as a later research
direction. The first `transactions` tasks follow that progression: understand
the professional work in static, inspectable matters before building the full
deal dance.

Compute companies interested in developing professional-work evaluations or
game-style environments for compute-market behavior and negotiation are
welcome to collaborate.
