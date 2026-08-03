# assess-commercial-fit

The first static `compute-bazaar-bench` Deal Room task.

The focal agent receives a closed synthetic matter for Project Northlink and
must assess whether a private 512-GPU B200 offer fits the buyer's mandate. The
room mixes controlling schedules, non-binding claims, technical records,
commercial paper, and peripheral documents.

## Capability

The task evaluates whether an agent can:

- reconcile buyer requirements with seller evidence;
- distinguish headline claims from controlling records;
- calculate all-in economics;
- identify every material technical and commercial gap;
- choose an appropriate deal disposition; and
- produce a cited, reviewable work product with concrete next actions.

It is one professional-work task, not a model leaderboard or a complete Deal
Room benchmark.

## Work Product

The agent must create:

- `/workspace/output/fit-assessment.json`
- `/workspace/output/deal-brief.md`

The JSON contract is visible at `/workspace/output-schema.json`. The brief must
stay consistent with the structured assessment.

## Environment

The main container exposes only the synthetic matter and output contract. The
agent runs as an unprivileged user. During the agent phase, network access is
allowlisted to OpenRouter so the closed matter remains the only research
corpus; other model providers can be added explicitly at run time.

The verifier runs in a separate no-network container. Hidden expected statuses
and grading logic are never copied into the agent image.

## Verification

The deterministic verifier applies strict all-pass grading. A task passes only
when every required criterion passes:

- typed output and opportunity identity;
- the correct terminal decision;
- all eleven requirement statuses;
- controlling buyer and seller evidence for each requirement;
- coverage and severity of every material issue;
- next-action coverage; and
- memo structure, consistency, and evidence breadth.

`criterion_pass_rate` and dimension scores remain diagnostics. They do not
convert a materially incomplete work product into a pass.

## Run

Validate configuration:

```sh
harbor run \
  -p evals/compute-bazaar-bench/deal-room-assess-commercial-fit \
  -a oracle \
  -e modal \
  --print-config
```

Run the reference solution:

```sh
harbor run \
  -p evals/compute-bazaar-bench/deal-room-assess-commercial-fit \
  -a oracle \
  -e modal \
  --job-name deal-room-assess-commercial-fit-oracle-001 \
  -o jobs-scratch
```

Run a real focal agent:

```sh
harbor run \
  -p evals/compute-bazaar-bench/deal-room-assess-commercial-fit \
  -a terminus-2 \
  -m openrouter/MODEL_ID \
  -e modal \
  --job-name deal-room-assess-commercial-fit-model-pilot-001 \
  -o jobs-scratch
```

The first real-agent run should be treated as a design audit. Read the complete
trajectory and verifier details before adding more tasks or models.
