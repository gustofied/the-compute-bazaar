# Transactions

**Question: Can an agent turn messy compute-deal material into accurate work without losing the terms that control the transaction?**

Transactions follows one fictional reserved-capacity deal through three pieces of work:

```text
buyer intent -> diligence room -> capacity agreement
normalize    -> organize       -> compare
```

| Task | Work | Deliverable |
| --- | --- | --- |
| [`normalize-buyer-mandate`](normalize-buyer-mandate/) | Reconcile a buyer's intake documents and open questions | Buyer mandate brief |
| [`draft-capacity-data-room-population-plan`](draft-capacity-data-room-population-plan/) | Decide what belongs in the room, who owns it, and when it should arrive | Data-room population plan |
| [`compare-capacity-agreement-against-term-sheet`](compare-capacity-agreement-against-term-sheet/) | Find where the draft agreement departs from the agreed terms | Agreement deviation report |

## Results

OpenCode 1.18.11 ran each model five times on each task. The table includes 43 completed documents: 15 from DeepSeek, 14 from GPT-5.6 Luna, and 14 from GLM 5.2.

| Model | Documents | Perfect documents | Requirements met | Buyer intake | Data room | Agreement review |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| DeepSeek V4 Flash 0731 | 15/15 | 1/15 | 84.3% | 78.9% | 94.3% | 80.6% |
| GPT-5.6 Luna | 14/15 | 1/14 | 90.0% | 90.7% | 96.7% | 84.8% |
| GLM 5.2 | 14/15 | 0/14 | 92.4% | 87.1% | 96.6% | 94.0% |

| Model | Median OpenCode time | Median total run time | Input tokens | Reused input | Output tokens |
| --- | ---: | ---: | ---: | ---: | ---: |
| DeepSeek V4 Flash 0731 | 328.6s | 446.5s | 160.1k | 131.6k | 8.7k |
| GPT-5.6 Luna | 118.2s | 257.9s | 271.1k | 271.1k | 7.2k |
| GLM 5.2 | 243.9s | 371.5s | 151.5k | 126.9k | 11.6k |

## What Happened

Diligence was the strongest task for every model, helped by a structured
evidence register and clear instructions. Agreement review separated the models
most clearly: GLM met 94.0% of the requirements, compared with 84.8% for Luna
and 80.6% for DeepSeek. Luna was fastest and strongest on buyer intake.

Only two of the 43 documents met every requirement. Making the final document
was a separate weakness: only one DOCX passed every quality check, and none of
the run records showed the agent previewing its finished document before
submission. Meeting most requirements did not reliably produce a clean, usable
document.

The same final checklist was applied to all 43 saved documents; the agents were
not rerun. One Luna attempt reached the one-hour limit and one GLM attempt ended
with a provider error, so neither was included. Each task was attempted five
times, and repeating a run may produce a different answer. The results cover
one connected fictional transaction and these exact model and OpenCode
combinations, not a broad model ranking.

## How It Grades

Each task requires one named DOCX file. The grader first checks that the file exists and is a valid document. It then checks the work against the source material and the task's requirements. The main score is the share of checklist items passed. A complete pass requires every item to pass.

Document quality is reviewed separately so a factually strong answer does not receive extra credit merely for looking polished, and a well-designed document cannot hide missing work.

## Source

The three kinds of work come from [Harvey's Legal Agent Benchmark](https://www.harvey.ai/blog/introducing-harveys-legal-agent-benchmark), but the compute transaction and its documents are original.

| Compute task | Harvey task form |
| --- | --- |
| Buyer mandate | [Extract disorganized client-intake facts](https://hub.harborframework.com/tasks/punitarani/trusts-estates-private-client-extract-client-intake-facts-scenario-01/latest) |
| Data-room plan | [Draft sell-side data-room population plan](https://hub.harborframework.com/tasks/punitarani/corporate-ma-draft-data-room-population-plan-scenario-01/latest) |
| Agreement comparison | [Compare PPA against term sheet](https://hub.harborframework.com/tasks/punitarani/energy-natural-resources-compare-power-purchase-agreement-against-term-sheet/latest) |

Each task keeps the structure of its Harvey counterpart while replacing the legal matter with compute-deal work across buyer intake, diligence, and contracting.
