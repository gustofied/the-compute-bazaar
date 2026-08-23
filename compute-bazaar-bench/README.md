# compute-bazaar-bench

[Harbor dataset](https://hub.harborframework.com/datasets/gustofied/compute-bazaar-bench)

A benchmark for evaluating agents on compute-market tasks, from transactions
and sourcing to market intelligence, risk, financing, and operations.

Large compute deals rarely happen in a single, transparent "venue". Buyer requirements,
supply, pricing, terms, diligence, and relationship history are spread across
messages, calls, spreadsheets, PDFs, data rooms, and people's memory. This
context has to be reconstructed, checked, and turned into action.

The benchmark brings together two complementary styles of environments.

### Compute Deal Work

Compute Deal Work starts with transactions: intake, diligence, and contracting.
Human relationships remain central, while agents may carry more of the analysis,
documentation, and operational volume around them. The products and commentary
from [Epilogue](https://epilogue.inc/) and
[ComputeDesk](https://www.compute-desk.com/) around compute desks and deal flow
motivate this direction.

[Harvey's Legal Agent Benchmark](https://www.harvey.ai/blog/introducing-harveys-legal-agent-benchmark)
provides the methodological starting point. Rather than inventing arbitrary
benchmark exercises, we begin with task forms that already represent real
professional work and test whether they transfer meaningfully into compute
transactions.

[**transactions**](evals/transactions/) evaluates agents on compute
deal work across intake, diligence, and contracting.

### Compute Market Games

Compute market games place agents inside changing compute-market processes,
including compute procurement, brokerage, matching, and negotiation. They are
more alive and interactive than closed professional-work evaluations, and their
stateful structure makes them more adaptable for training.
The first implemented environment is
[`reliability-is-blind`](evals/reliability-is-blind/).

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
    `-- <harbor-job>/
```

Open the Compute Bazaar Terminal and enter `eval`:

```bash
compute-bazaar terminal
```

Then run an evaluation from the Terminal shell with Harbor:

```bash
harbor run \
  -p compute-bazaar-bench/evals/reliability-is-blind/harbor \
  -a AGENT \
  -m MODEL \
  -e ENVIRONMENT \
  -o compute-bazaar-bench/jobs
```

You can also run Harbor directly from any shell.

Browse the resulting jobs with Harbor's native viewer:

```bash
cd compute-bazaar-bench
harbor view jobs
```

### Tourneys

I created something I call Tourneys to pair with the evals: controlled
comparisons where agents face the same tasks under the same conditions. As we
know, it is one thing to compare models on an eval, but to ensure fair
comparisons, it is also important to fix the harness, temperature, and other
factors that may affect the model's output.

## Evaluations

### [transactions](evals/transactions/)

The first three tasks cover buyer requirements, data-room planning, and
agreement review:

```text
messy intent -> organized evidence process -> controlled transaction paper
analyze      -> draft                      -> review
```

> Can an agent perform the professional work required to advance a compute
> transaction accurately, with evidence, and without losing the deal's
> controlling terms?

### [reliability-is-blind](evals/reliability-is-blind/)

`reliability-is-blind` is an interactive compute-brokerage evaluation. An agent
repeatedly places supply into deals and learns which suppliers to trust from
delivery outcomes without being told which supplier caused a failure.
