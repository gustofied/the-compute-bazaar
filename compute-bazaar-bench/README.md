# compute-bazaar-bench

[Harbor dataset](https://hub.harborframework.com/datasets/gustofied/compute-bazaar-bench)

A benchmark for evaluating agents on compute-market tasks.

> hey, i mix eval/evaluation/task/env, they are the same thing btw

The benchmark brings together two complementary styles of environments:

### Compute Deal Work

Using [Harvey's Legal Agent Benchmark](https://www.harvey.ai/blog/introducing-harveys-legal-agent-benchmark) gives this family of evaluations methodological grounding. Instead of inventing benchmark tasks from scratch, we start with task forms that already represent real professional work and test whether they transfer meaningfully into compute transactions.

The products and commentary from [Epilogue](https://epilogue.inc/) and
[ComputeDesk](https://www.compute-desk.com/) around compute desks and deal flow
motivate the work here, especially their interest in involving agents.

[**transactions**](evals/transactions/README.md) evaluates agents on compute
deal work across intake, diligence, and contracting.

### Compute Market Games

Compute market games place agents inside changing compute-market processes,
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

Open the Compute Bazaar Terminal and enter `eval`:

```bash
compute-bazaar terminal
```

Then run an evaluation from the Terminal shell with Harbor:

```bash
harbor run \
  -p compute-bazaar-bench/evals/reliability-is-blind/task \
  -a AGENT \
  -m MODEL \
  -e ENVIRONMENT \
  -o compute-bazaar-bench/jobs/raw
```

You can also run Harbor directly from any shell.

## Evaluations

### [transactions](evals/transactions/README.md)

Its first three tasks move through intake, diligence, and contracting:

```text
messy intent -> organized evidence process -> controlled transaction paper
analyze      -> draft                      -> review
```

> Can an agent perform the professional work required to advance a compute
> transaction accurately, with evidence, and without losing the deal's
> controlling terms?

### [reliability-is-blind](evals/reliability-is-blind/README.md)

`reliability-is-blind` is an interactive compute-brokerage evaluation. An agent
repeatedly places supply into deals and learns which suppliers to trust from
delivery outcomes without being told which supplier caused a failure.
