# Transactions release v1

Four models are shown on the same three linked synthetic compute-transaction tasks. Mistral Small was run fresh in Harbor. The DeepSeek, GPT-5.6 Luna, and GLM rows use their earlier saved documents, regraded with the same release grader; those agents were not rerun.

Strict all-pass means one attempt passed every required check. Criterion pass is shown only when a usable document reached checklist review. A missing or invalid required file receives a benchmark zero at the output gate.

The grader was corrected during private calibration. Every score shown here uses the frozen release grader.

## Results

| Model | How scored | Scored / planned | Strict all-pass | Criterion pass | Equal-task average | Document quality | Median agent time | Median input / output tokens | Agent cost | Judge cost | Modal cost |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Mistral Small 2603 | Fresh Harbor run | 14/15 | 0/14 (0.0%) | not judged (output gate) | 0.0% (output gate) | not reviewable | 37.3s | 95,114 / 1,268 | - | $0.000 | - |
| DeepSeek V4 Flash 0731 | Earlier output, regraded | 15/15 | 1/15 (6.7%) | 721/855 (84.3%) | 84.6% | 0/10/5 good/mixed/poor | 328.6s | 160,056 / 8,652 | - | - | - |
| GPT-5.6 Luna | Earlier output, regraded | 14/15 | 1/14 (7.1%) | 722/802 (90.0%) | 90.8% | 1/6/7 good/mixed/poor | 118.2s | 271,112 / 7,210 | - | - | - |
| GLM 5.2 | Earlier output, regraded | 14/15 | 0/14 (0.0%) | 733/793 (92.4%) | 92.6% | 0/9/5 good/mixed/poor | 243.9s | 151,482 / 11,642 | - | - | - |

## What this showed

- Mistral Small produced 0 usable DOCX files in 15 attempts. 14 attempts were scored as model-output failures, not hidden or discarded.
- An invalid DOCX receives zero across the task checklist without a GPT-5.4 review of the mislabeled file. This tests whether the model and harness can deliver the requested work product; it does not prove that no useful analysis appeared in the underlying trace.
- 1 Mistral attempt was excluded under the frozen one-hour timeout rule. A timeout does not identify its cause.
- 9 Mistral attempts: deliverable is not a valid DOCX archive
- 1 Mistral attempt: deliverable size is outside the accepted range: 38 bytes
- 2 Mistral attempts: required deliverable not produced: capacity-agreement-deviation-report.docx
- 2 Mistral attempts: required deliverable not produced: capacity-data-room-population-plan.docx
- Recorded tool calls show that 10/14 scored attempts tried to read an Office file directly, 11/14 encountered at least one tool error, and none reopened or existence-checked the final file. These are trace indicators, not proof of a single cause.
- The larger-model rows often passed most individual checks, while passing every check in one attempt remained rare.
- Document quality is kept separate from task accuracy. A malformed or missing DOCX is an output failure and is not given a visual-quality rating.

## Per task

| Model | Task | Scored | Strict all-pass | Mean criterion pass |
| --- | --- | ---: | ---: | ---: |
| Mistral Small 2603 | `normalize-buyer-mandate` | 5 | 0/5 | not judged (output gate) |
| Mistral Small 2603 | `draft-capacity-data-room-population-plan` | 5 | 0/5 | not judged (output gate) |
| Mistral Small 2603 | `compare-capacity-agreement-against-term-sheet` | 4 | 0/4 | not judged (output gate) |
| DeepSeek V4 Flash 0731 | `normalize-buyer-mandate` | 5 | 0/5 | 78.9% |
| DeepSeek V4 Flash 0731 | `draft-capacity-data-room-population-plan` | 5 | 1/5 | 94.3% |
| DeepSeek V4 Flash 0731 | `compare-capacity-agreement-against-term-sheet` | 5 | 0/5 | 80.6% |
| GPT-5.6 Luna | `normalize-buyer-mandate` | 5 | 0/5 | 90.7% |
| GPT-5.6 Luna | `draft-capacity-data-room-population-plan` | 4 | 1/4 | 96.7% |
| GPT-5.6 Luna | `compare-capacity-agreement-against-term-sheet` | 5 | 0/5 | 84.8% |
| GLM 5.2 | `normalize-buyer-mandate` | 5 | 0/5 | 87.1% |
| GLM 5.2 | `draft-capacity-data-room-population-plan` | 5 | 0/5 | 96.6% |
| GLM 5.2 | `compare-capacity-agreement-against-term-sheet` | 4 | 0/4 | 94.0% |

## Cost

The OpenRouter account balance fell by `$0.116991` during the fresh official job. No Mistral document reached checklist review, so the fresh job made zero GPT-5.4 grading calls. Per-trial agent cost and Modal cost were not available.
The preserved-output replay used `$8.854735` across 129 GPT-5.4 grading calls. That total covers DeepSeek, GPT-5.6 Luna, and GLM together and is not split by model.

## Limits

This is one synthetic transaction followed through three related tasks, with five unseeded attempts per task. It is a descriptive result for this fixed harness, not a general model ranking or a claim about broad compute-market competence.

The table deliberately marks how each row was produced. Mistral is a fresh native Harbor run; the other rows are preserved documents regraded later with the same release grader.

The Mistral route retained the requested Exacto model string, but OpenRouter did not expose the downstream backend identity. Sampling was unseeded, and GPT-5.4 made one judgment per checklist item.
