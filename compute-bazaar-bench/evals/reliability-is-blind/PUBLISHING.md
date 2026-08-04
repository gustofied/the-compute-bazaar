# Publishing Reliability Is Blind

Reliability Is Blind is published as the Harbor task
`gustofied/reliability-is-blind`. It belongs to the umbrella dataset
`gustofied/compute-bazaar-bench`, alongside the other Compute Bazaar tasks.

The umbrella dataset points to task digest
`sha256:5781edcec052d4050e4e87127fb6572063e10e9858609fb71fa652ea04520e41`.

## Public Surface

The task publication contains:

- the Harbor package in `task/`;
- no raw jobs, private protocol manifests, analyzer output, or research
  checkout.

The task reward is a signed mean broker reward, not accuracy or pass rate.
Harbor job pages should be read with the task's delivery rate, completion, and
reliability-target metrics beside the headline reward.

## Historical Jobs

The Mistral protocol ran against task digest
`sha256:b20b5ef7db8a74484830396101904582c0727540a85dd978f71f6210e1583977`.
The raw jobs preserve that digest, but an exact publishable source snapshot for
it is not currently available. The nearest committed pre-cleanup task
reconstructs to a different digest. Do not imply that publishing the current
task retroactively supplies the historical package.

The first public job sample should use the three cells selected before model
outcomes were observed:

- `reliability-is-blind-mistral-matched-20-rib-001`
- `reliability-is-blind-mistral-matched-20-rib-011`
- `reliability-is-blind-mistral-matched-20-rib-016`

Together they contain nine planned Mistral trials across easy, uncertain, and
high-risk opening markets. Keep them local unless either the exact historical
package is recovered or the upload is explicitly described as a historical
local-source job with an unavailable package revision.

The complete 20-seed run remains exploratory. It includes two Mistral Large
deadlines and one manually interrupted parent job, so it must not be presented
as a clean leaderboard.

## Never Publish

- `.secrets/` or the private seed-keyed protocol manifest;
- evaluator output containing hidden supplier diagnostics;
- `references/`, local virtual environments, or caches;
- provider credentials or environment files.

Public job uploads expose ATIF trajectories, protected ledgers, artifacts, and
recorded market seeds. Once uploaded, those seeds are public protocol cases and
must not be described as uncontaminated hidden evaluation seeds.

## Commands

Authenticate, then publish the task and umbrella dataset:

```bash
harbor auth login
harbor publish compute-bazaar-bench/evals/reliability-is-blind/task --public
harbor publish compute-bazaar-bench --public
```

Only after the historical source limitation is resolved or explicitly accepted,
upload the predeclared job sample:

```bash
harbor upload compute-bazaar-bench/jobs/raw/reliability-is-blind-mistral-matched-20-rib-001 --public
harbor upload compute-bazaar-bench/jobs/raw/reliability-is-blind-mistral-matched-20-rib-011 --public
harbor upload compute-bazaar-bench/jobs/raw/reliability-is-blind-mistral-matched-20-rib-016 --public
```

After publication, download the dataset and one trial into a temporary
directory and verify that the task, ATIF trajectory, verifier output, artifacts,
and ledger render correctly from the registry copies.
