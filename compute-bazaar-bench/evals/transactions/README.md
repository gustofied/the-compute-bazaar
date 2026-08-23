# Transactions

**Question: Can an agent turn messy compute-deal material into accurate work without losing the terms that control the transaction?**

The Transactions benchmark follows one fictional GPU capacity deal through
three pieces of work:

```text
buyer requirements -> diligence room -> compute services agreement
normalize          -> organize       -> compare
```

| Task                                                                                              | Work                                                                    | Deliverable                |
| ------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- | -------------------------- |
| [`normalize-buyer-mandate`](normalize-buyer-mandate/)                                             | Reconcile a buyer's requirements and open questions                     | Buyer mandate brief        |
| [`draft-capacity-data-room-population-plan`](draft-capacity-data-room-population-plan/)           | Decide what belongs in the room, who owns it, and when it should arrive | Data-room population plan  |
| [`compare-capacity-agreement-against-term-sheet`](compare-capacity-agreement-against-term-sheet/) | Find where the draft agreement departs from the agreed terms            | Agreement deviation report |

## Results

OpenCode 1.18.11 ran each model five times on each task. The table includes 43 completed documents: 15 from DeepSeek, 14 from GPT-5.6 Luna, and 14 from GLM 5.2.

| Model                  | Runs scored | Run pass rate | Criterion pass rate | Buyer intake | Data room | Agreement review |
| ---------------------- | ----------: | ------------: | ------------------: | -----------: | --------: | ---------------: |
| DeepSeek V4 Flash 0731 |       15/15 |   1/15 (6.7%) |               84.3% |        78.9% |     94.3% |            80.6% |
| GPT-5.6 Luna           |       14/15 |   1/14 (7.1%) |               90.0% |        90.7% |     96.7% |            84.8% |
| GLM 5.2                |       14/15 |   0/14 (0.0%) |               92.4% |        87.1% |     96.6% |            94.0% |

| Model                  | Median OpenCode time | Median total run time | Input tokens | Reused input | Output tokens |
| ---------------------- | -------------------: | --------------------: | -----------: | -----------: | ------------: |
| DeepSeek V4 Flash 0731 |               328.6s |                446.5s |       160.1k |       131.6k |          8.7k |
| GPT-5.6 Luna           |               118.2s |                257.9s |       271.1k |       271.1k |          7.2k |
| GLM 5.2                |               243.9s |                371.5s |       151.5k |       126.9k |         11.6k |

## What Happened

All three models completed most of the requested work, but almost none completed
everything. GLM covered the most requirements overall at 92.4%, followed by
Luna at 90.0% and DeepSeek at 84.3%. Even so, only one DeepSeek run and one Luna
run passed the complete rubric. None of the GLM runs did.

For this kind of work, the document has to be delivered in full. Covering nine
out of ten requirements can still mean missing a term, warning, owner, or next
action that matters. Following Harvey LAB, a run therefore passes only when
every requirement passes.

All three models were strongest on the data-room task, where the structured
evidence register and clear instructions made the work easier to organize.
DeepSeek nearly matched the others there but fell behind on buyer intake and
agreement review. Luna was the fastest model and strongest on buyer intake. GLM
was strongest on agreement review, covering 94.0% of its requirements compared
with 84.8% for Luna and 80.6% for DeepSeek, but its small omissions still
prevented an all-pass run.

This is still a small first benchmark built around one fictional transaction,
with plenty of room for harder and more realistic tasks. Publishing it gives me
a concrete base to keep building from and, I hope, gives other people ideas for
what agent evaluation in compute markets could become.

## How It Grades

The criterion pass rate shows how many individual requirements were met. A run passes only when every requirement is met, following Harvey LAB's all-pass standard.

Document quality is reviewed separately so a factually strong answer does not receive extra credit merely for looking polished, and a well-designed document cannot hide missing work.

## Source

The three task forms come from [Harvey's Legal Agent Benchmark](https://www.harvey.ai/blog/introducing-harveys-legal-agent-benchmark), but the compute transaction and its documents are original. Thanks to [Punit Arani](https://x.com/punit_arani) for converting the Harvey tasks into Harbor tasks.

| Compute task         | Harvey task form                                                                                                                                                          |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Buyer mandate        | [Extract disorganized client-intake facts](https://hub.harborframework.com/tasks/punitarani/trusts-estates-private-client-extract-client-intake-facts-scenario-01/latest) |
| Data-room plan       | [Draft sell-side data-room population plan](https://hub.harborframework.com/tasks/punitarani/corporate-ma-draft-data-room-population-plan-scenario-01/latest)             |
| Agreement comparison | [Compare PPA against term sheet](https://hub.harborframework.com/tasks/punitarani/energy-natural-resources-compare-power-purchase-agreement-against-term-sheet/latest)    |

Each task keeps the structure of its Harvey counterpart while replacing the
legal matter with compute-deal work across buyer requirements, diligence, and
agreement review.
