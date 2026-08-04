# compute-bazaar-bench

A benchmark for agents working in compute markets.

The benchmark takes methodological inspiration from
[Harvey's Legal Agent Benchmark](https://www.harvey.ai/blog/introducing-harveys-legal-agent-benchmark).
Rather than inventing arbitrary benchmark forms, it starts from tasks that
already represent real professional work and tests whether those forms transfer
meaningfully into compute markets.

The market motivation comes from the opaque deal flow around
[Epilogue](https://epilogue.inc/),
[ComputeDesk](https://www.compute-desk.com/), and
[live compute inventory](https://www.computedesk.live/): bespoke opportunities,
fragmented communications, technical and commercial diligence, and controlling
terms that must survive a transaction's movement from conversation to paper.

This gives `compute-bazaar-bench` a recognizable methodological lineage while
leaving the compute documents, risks, calculations, and professional standards
to be developed from the domain itself.

## Structure

```text
compute-bazaar-bench/
|-- dataset.toml
|-- evals/
|   |-- reliability-is-blind/
|   `-- transactions/
|-- viewer/
`-- jobs/                         local only
    |-- raw/                      Harbor jobs
    `-- reports/                  normalized viewer reports
```

Task source and benchmark metadata are versioned. Generated jobs, reports, and
private evaluator material remain local.

## Evaluations

### [transactions](evals/transactions/README.md)

`transactions` evaluates professional work that moves an OTC or
reserved-compute transaction from initial intent toward executable paper.

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
