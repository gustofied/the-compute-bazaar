# Windmill

This is the optional hosted scheduler. The same market cycle can run locally
with `compute-bazaar market refresh`; AutoMQ and AWS are not required.

No active Windmill deployment is required or assumed. This directory is kept
for a future hosted deployment.

When enabled, Windmill runs two scheduled Python jobs:

- `market_hourly.py` calls `run_market_hourly()`.
- `sandbox_benchmark_weekly.py` imports new public StarSling results and rebuilds
  the measured-workload Gold/public output.

The market job pulls providers, writes Bronze and Silver, runs the DataFusion
SQL models, writes GPU Gold, publishes JSON, and writes the market-run manifest.
There are no separate provider schedules.

## Access

The worker runs inside the AutoMQ VPC. Windmill and AutoMQ listen only on the
EC2 host, so update the laptop SSH rule and open a tunnel:

```bash
uv run python infra/aws/refresh_runtime_access.py \
  --profile YOUR_AWS_PROFILE \
  --security-group-id YOUR_SECURITY_GROUP_ID \
  --prune-stale

ssh -i .secrets/compute-bazaar-automq-runtime.pem \
  -o ExitOnForwardFailure=yes \
  -L 8080:127.0.0.1:8080 \
  -L 18081:127.0.0.1:8081 \
  ec2-user@RUNTIME_HOST
```

- AutoMQ: `http://127.0.0.1:8080`
- Windmill: `http://127.0.0.1:18081`

The different local Windmill port avoids collisions with local development
services. Do not open the runtime's ports 8080 or 8081 in the public security
group.

## Worker image

Deploy through the revision-pinned helper. It archives one committed revision,
builds that exact source on the runtime, updates only the worker service, and
fails unless the running container reports the requested revision:

```bash
uv run python infra/windmill/deploy_worker.py \
  --host ec2-user@RUNTIME_HOST \
  --revision HEAD
```

Do not update `WM_WORKER_IMAGE` by hand. A Git push does not deploy the worker.
After deploying renderer changes, run the market job once. If the workload
renderer changed, run the StarSling job once too. Then verify all three card
families against the exact deployed revision:

```bash
uv run python infra/aws/check_public_market.py \
  --base-url "$COMPUTE_BAZAAR_PUBLIC_BASE_URL" \
  --require-renderer-revision "$(git rev-parse HEAD)"
```

The check covers GPU index, Prime availability, and measured workload cards.
It fails on an old render profile, missing card variant, unknown producing
revision, or a revision that differs from the requested commit.

Render profiles are content-derived from each card renderer, its shared chart
code, metadata, page template, and fonts. Editing any of those inputs changes
the immutable publication path automatically. Do not add manual renderer
version numbers.

The equivalent manual build is retained below for debugging only.

Build from the repository root:

```bash
docker build \
  -f infra/windmill/self-host/Dockerfile.worker \
  --build-arg COMPUTE_BAZAAR_REVISION=$(git rev-parse HEAD) \
  -t compute-bazaar-windmill-worker:YYYY-MM-DD-description \
  .
```

The image installs this uv project. Put credentials in Windmill secrets or use
the EC2 IAM role. Do not add them to the image.

## Windmill variables

```text
AWS_REGION
COMPUTE_BAZAAR_RAW_ROOT
COMPUTE_BAZAAR_LAKE_ROOT
COMPUTE_BAZAAR_DASHBOARD_OUTPUT_ROOT
COMPUTE_BAZAAR_PUBLIC_BASE_URL
COMPUTE_BAZAAR_KAFKA_BOOTSTRAP_SERVERS
COMPUTE_BAZAAR_KAFKA_SECURITY_PROTOCOL
COMPUTE_BAZAAR_KAFKA_SASL_MECHANISM
COMPUTE_BAZAAR_KAFKA_USERNAME
COMPUTE_BAZAAR_KAFKA_PASSWORD
provider API keys
```

## Schedules

Create or update both schedules through the private tunnel:

```bash
export WINDMILL_TOKEN=...
export WINDMILL_WORKSPACE=compute-bazaar

uv run python infra/windmill/bootstrap_market_schedule.py
uv run python infra/windmill/bootstrap_sandbox_benchmark_weekly_schedule.py
```

The market schedule's default six-field cron is hourly:

```text
0 0 * * * *
```

The StarSling job only reads results published in its public repository. It
polls weekly, does not run paid workloads, and does not depend on the hourly
GPU job. Its chart uses the measured dates retained in the source; it does not
create daily observations between source runs.

Run the market job manually with:

```bash
uv run python infra/windmill/bootstrap_market_schedule.py \
  --run-now \
  --wait \
  --run-id market-manual-YYYYMMDD
```

Verify freshness and one-run alignment across the market manifest, GPU cards,
and portable lake with:

```bash
uv run python infra/aws/check_public_market.py \
  --base-url "$COMPUTE_BAZAAR_PUBLIC_BASE_URL"
```

## Self-hosted development stack

`self-host/docker-compose.yml` runs Postgres, the Windmill server and worker,
and Caddy. Real values belong in `/opt/windmill/.env`.

The worker currently uses `privileged: true` and `DISABLE_NSJAIL=true`. Do not
use this compose file on a public or multi-tenant host. A production worker
should use Windmill's sandbox image path and should not run privileged.

```bash
cd /opt/windmill
sudo docker compose ps
curl -sS http://127.0.0.1:18081/api/version
```
