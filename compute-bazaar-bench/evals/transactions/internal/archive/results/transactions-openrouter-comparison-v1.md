# Transactions OpenRouter comparison v1

> **Adjudication correction:** verifier v2 was replayed over the same 43 preserved DOCX outputs with no agent rerun. The original Harbor scores below remain frozen. Adam required Modal before Gate 2; the [protocol amendment](../adjudication/adjudication-replay-001.modal-amendment.json) records that authorized change from the Gate 1 Docker plan.

This comparison used the same three CB-2026-041 tasks, OpenCode 1.18.11,
Modal, RewardKit 0.1.7, and frozen GPT-5.4 judge for every selected model.
Each model received five unseeded attempts per task.

## Original frozen Harbor scores (verifier v1)

| Model | Retained | Macro semantic | Intake | Diligence | Contracting | All pass |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| DeepSeek V4 Flash 0731 | 15/15 | 0.8492 | 0.8000 | 0.9509 | 0.7968 | 0/15 |
| GPT-5.6 Luna | 14/15 | 0.9049 | 0.9071 | 0.9528 | 0.8548 | 0/14 |
| GLM 5.2 | 14/15 | 0.9097 | 0.8786 | 0.9472 | 0.9032 | 0/14 |

The pooled criterion diagnostics were `723/855` for DeepSeek, `721/802` for
Luna, and `721/793` for GLM. Equal-task macro semantic score is the primary
diagnostic; pooled criteria are shown only alongside it.

## Amended adjudicated scores (verifier v2 replay)

| Model | Retained | All pass | Macro semantic | Criterion pass |
| --- | ---: | ---: | ---: | ---: |
| DeepSeek V4 Flash 0731 | 15 | 1/15 | 0.8464 | 721/855 (84.3%) |
| GPT-5.6 Luna | 14 | 1/14 | 0.9075 | 722/802 (90.0%) |
| GLM 5.2 | 14 | 0/14 | 0.9257 | 733/793 (92.4%) |

Strict all-pass is the headline. Macro semantic and pooled criterion pass are diagnostics.

## What It Shows

- The ordering survives correction: GLM, Luna, then DeepSeek on equal-task macro semantic score.
- Diligence remains the strongest checkpoint. Contract review creates the largest separation, with amended means of `0.9395` for GLM, `0.8484` for Luna, and `0.8065` for DeepSeek.
- Two diligence outputs pass every amended criterion. The verifier-v2 strict all-pass headline is `2/43`.
- `131/2,450` criterion decisions differed between verifier v1 and v2 on byte-identical outputs, with 11 net additional passes. Because criterion framing and evidence context changed and both adjudications were unseeded, 5.3% is procedure disagreement, not a judge-repeatability estimate.
- Verifier v2 replaces the unsupported C-058 deadline test with a source-supported site-control test and supplies complete normalized or criterion-specific evidence.

## Document Craft

| Model | Reviewed | Good | Mixed | Poor |
| --- | ---: | ---: | ---: | ---: |
| DeepSeek V4 Flash 0731 | 15 | 0 | 10 | 5 |
| GPT-5.6 Luna | 15 | 1 | 7 | 7 |
| GLM 5.2 | 14 | 0 | 9 | 5 |

The blind review covered 44 documents and 428 rendered pages. Only one document
passed every craft criterion; 17 had a critical clipping, overlap, rendering,
body, or table-readability failure. Craft includes one collected document from
a later infrastructure-excluded trial, so it is not a semantic denominator.
The page-level ratings are in the
[visual review](transactions-openrouter-comparison-v1.visual-review.json).

All 43 retained trajectories contained an observed post-draft structural or
path check, but none invoked a renderer on the output before submission. The
agents revised after those checks in `4/15` DeepSeek, `6/14` Luna, and `1/14`
GLM retained traces. These are command indicators, not claims about reasoning.

## Denominator

The frozen plan contained 75 official slots. Mistral Small 2603 failed its
canary gate, so 15 slots were withheld. Sixty trials were launched. The complete
Claude Sonnet 4.6 job was infrastructure-invalidated after the evaluation budget
was exhausted; all 15 slots and its eight otherwise usable trials are excluded,
with no Claude score. The selected comparison therefore contains 45 official
slots, 43 retained trials, and two trial-level infrastructure exclusions.

The selected jobs are:

- `transactions-comparison-v1-deepseek-v4-flash-0731-001`
- `transactions-comparison-v1-gpt-5.6-luna-001`
- `transactions-comparison-v1-glm-5.2-001`

The comparison was Git-precommitted at
`7890fd06b1c6d2284af693124b61b61e85399be6`. A byte-preserving spreadsheet
tracking repair followed at `a8495f0fab6546d9be49e59333081927a6a6fac1`; task
digests did not change.

The frozen [commitment](../protocols/transactions-comparison-v1.commitment.json)
and post-run [run record](../protocols/transactions-comparison-v1.run.json)
retain the exact model IDs, task and lock digests, canary history, routing
limits, and denominator decision.

Agent dollar cost and exact replay-only Modal dollars remain unavailable. The
adjudication replay's OpenRouter key/account differential was `$8.854735` for
129 completed GPT-5.4 semantic judge batches. There were no replay-level retries
or recorded judge errors; provider-internal retries, per-call identities, and the
actual downstream provider behind OpenRouter Exacto were not retained.

This is a descriptive comparison on three linked checkpoints from one synthetic
matter. It does not establish statistical significance, general model
superiority, independent-matter accuracy, or broad compute-market competence.
GPT-5.4 also judged GPT-5.6 Luna outputs; possible same-family correlated bias
was not measured.
