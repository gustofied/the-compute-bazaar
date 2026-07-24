# Windmill GPU Price Ingestion

This is the near-term orchestration path for provider pulls.

## Why Windmill Now

Use Windmill for the hourly provider jobs because it gives us scheduling, run history,
manual reruns, logs, and simple operator controls without introducing a durable workflow
engine too early. Temporal can wait until we have multi-step agent/control-flow work that
needs durable state, retries across many activities, and human/agent approvals.

## Network Shape

The AutoMQ endpoint is private:

```text
*.automq.private:9102
```

That means the Windmill worker that runs the producer must be inside the AWS VPC, or otherwise
connected to it through VPN/private networking. Windmill Cloud can still be the control plane if
the executing worker is in the VPC. A public worker outside the VPC will fail DNS resolution.

## Worker Image

Build this image from the repository root:

```sh
docker build \
  -f infra/windmill/self-host/Dockerfile.worker \
  -t compute-bazaar-windmill-worker:2026-06-17 \
  .
```

The `.dockerignore` file excludes `.env`, `.secrets`, local notes, data, and git metadata from the
build context.

For Windmill jobs, there are two good shapes:

1. For this dev EC2 stack, use a custom Windmill worker image with this package baked in. That lets
   `infra/windmill/vast_hourly.py` run as a normal Windmill Python script.
2. Later, use the official `# sandbox <image>` flow once the provider image is in a registry the VPC
   worker can pull from. That keeps job execution daemonless: no Docker socket, no Docker-in-Docker
   sidecar, and no host filesystem escape route.

## Self-Hosted Dev Windmill

The current dev deployment runs on the AutoMQ runtime EC2 host because that host is already inside
the VPC and can resolve the private AutoMQ broker DNS names.

Files for the repeatable shape are in `infra/windmill/self-host/`:

```text
self-host/.env.example
self-host/Caddyfile
self-host/Dockerfile.worker
self-host/docker-compose.yml
```

On the EC2 host, the live files sit under `/opt/windmill`. The UI is bound to localhost on the
host, so do not open a public security-group port for it. Tunnel from your laptop instead:

```sh
ssh -i .secrets/compute-bazaar-automq-runtime.pem \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -L 8081:127.0.0.1:8081 \
  ec2-user@HOST
```

Then open:

```text
http://127.0.0.1:8081
```

If the laptop is on mobile/5G, the public IP can drift and the security group will stop allowing
the tunnel. Refresh the current `/32` before opening the tunnel:

```sh
uv run python infra/aws/refresh_runtime_access.py --profile YOUR_AWS_PROFILE
```

Add `--dry-run` to preview, and add `--prune-stale` after this helper has created older managed
rules that should be removed.

Complete the first login/sign-up flow in the UI, then rotate any bootstrap password immediately.

Useful host checks:

```sh
cd /opt/windmill
sudo docker compose ps
curl -sS http://127.0.0.1:8081/api/health/status
```

To refresh the baked project CLI on the dev EC2 host, sync a secret-free build context to the
host, rebuild the worker image, and recreate only the worker service:

```sh
rsync -az --delete \
  --exclude '.git' \
  --exclude '.venv' \
  --exclude '.env' \
  --exclude '.secrets' \
  --exclude 'notes' \
  --exclude 'data' \
  ./ ec2-user@HOST:/home/ec2-user/compute-bazaar-worker-build/

ssh ec2-user@HOST '
  cd /home/ec2-user/compute-bazaar-worker-build &&
  sudo docker build -f infra/windmill/self-host/Dockerfile.worker \
    -t compute-bazaar-windmill-worker:2026-06-17 . &&
  cd /opt/windmill &&
  sudo docker compose up -d --force-recreate windmill_worker
'
```

The dev runtime has a 20 GiB root volume. Repeated image builds can leave
several gigabytes of unused BuildKit cache even when every service is healthy.
Before a rebuild, inspect rather than guessing:

```sh
df -h /
sudo docker system df
```

If only the build cache is reclaimable, `sudo docker builder prune -a -f`
removes unused build layers without touching active images, containers,
volumes, Postgres, or Windmill state. Do not prune volumes. The longer-term
production shape is a registry-built worker image rather than building on this
small runtime host.

## Required Environment

Set these as Windmill variables/secrets or worker environment variables:

```text
AWS_REGION=eu-west-3
AWS_DEFAULT_REGION=eu-west-3
COMPUTE_BAZAAR_RAW_ROOT=s3://YOUR_BUCKET/raw
COMPUTE_BAZAAR_LAKE_ROOT=s3://YOUR_BUCKET/lake
COMPUTE_BAZAAR_KAFKA_BOOTSTRAP_SERVERS=...
COMPUTE_BAZAAR_KAFKA_SECURITY_PROTOCOL=SASL_PLAINTEXT
COMPUTE_BAZAAR_KAFKA_SASL_MECHANISM=SCRAM-SHA-256
COMPUTE_BAZAAR_KAFKA_USERNAME=...
COMPUTE_BAZAAR_KAFKA_PASSWORD=...
VAST_API_KEY=...
LIUM_API_KEY=...
```

Public connectors need no secret. Optional authenticated connectors are added
to the schedule when their matching environment variable from
`.env.example` is present.

Prefer an AWS IAM role attached to the worker compute. Do not put AWS access keys in Windmill
unless there is no alternative.

For ECS-hosted Windmill workers, Windmill documents that AWS credential/region environment
variables need to be whitelisted so scripts can use AWS APIs:

```text
AWS_EXECUTION_ENV,AWS_CONTAINER_CREDENTIALS_RELATIVE_URI,AWS_DEFAULT_REGION,AWS_REGION
```

## Windmill Scripts

The main script is `infra/windmill/market_hourly.py`. It runs the complete heartbeat:

```text
ingest live APIs -> ingest current price observations -> ingest published rate cards -> build GPU gold -> export GPU history -> build sandbox-cost gold -> export dashboard JSON -> write market run manifest
```

In the dev worker image it shells out to the baked project CLI:

```text
/opt/compute-bazaar/.venv/bin/gpu-prices market-hourly
```

`infra/windmill/vast_hourly.py` and `infra/windmill/lium_hourly.py` remain useful for provider-only
debugging. They shell out to:

```text
/opt/compute-bazaar/.venv/bin/gpu-prices ingest-vast
/opt/compute-bazaar/.venv/bin/gpu-prices ingest-lium
```

Recommended schedule:

```text
0 0 * * * *
```

That is hourly in Windmill's six-field cron format. Start hourly until we understand Vast API limits
and cost/noise. We can tighten to every 15 minutes later if the market data is useful enough.

Suggested schedule args, using Windmill variables/secrets:

```json
{
  "vast_api_key": "$var:f/compute-bazaar/vast_api_key",
  "lium_api_key": "$var:f/compute-bazaar/lium_api_key",
  "raw_root": "$var:f/compute-bazaar/raw_root",
  "lake_root": "$var:f/compute-bazaar/lake_root",
  "dashboard_output_root": "$var:f/compute-bazaar/dashboard_output_root",
  "automq_bootstrap_servers": "$var:f/compute-bazaar/kafka_bootstrap_servers",
  "kafka_security_protocol": "SASL_PLAINTEXT",
  "kafka_sasl_mechanism": "SCRAM-SHA-256",
  "kafka_username": "$var:f/compute-bazaar/kafka_username",
  "kafka_password": "$var:f/compute-bazaar/kafka_password",
  "aws_region": "eu-west-3",
  "topic_prefix": "gpu",
  "providers": "vast,lium,spheron,inference_sh,gridstackhub,cloud_gpu_prices,thunder_compute,vultr,scaleway,oracle_cloud,ovhcloud,clore,akash,aws_spot,azure,runpod,verda,published_rate_cards",
  "lium_size": 200,
  "lium_max_pages": 10,
  "lium_paginate": true,
  "dashboard_limit": 100,
  "dry_run": false
}
```

After first login, create a Windmill API token and run the bootstrap helper over the SSH tunnel:

```sh
export WINDMILL_TOKEN=...
export WINDMILL_WORKSPACE=compute-bazaar
uv run python infra/windmill/bootstrap_market_schedule.py
```

The helper reads the required provider/Kafka/S3 values from your local environment, creates them as
Windmill variables/secrets, creates the market script, and adds the hourly schedule. It also creates
`dashboard_output_root`, deriving `s3://.../dashboard/compute-bazaar` from `COMPUTE_BAZAAR_LAKE_ROOT`
when `COMPUTE_BAZAAR_DASHBOARD_OUTPUT_ROOT` is not set.

The same hourly run writes `sandbox-cost.json` beside the GPU dashboard files.
Sandbox price evidence is reviewed and versioned in the project; the hourly job
does not scrape provider marketing pages. The public StarSling benchmark
repository is checked separately each day by
`.github/workflows/sandbox-cost-sources.yml`. A failed check means new evidence
or schema drift needs review. After review, update canonical evidence with the
commit-pinned `sandbox-cost refresh-benchmark --update-evidence` command in
`docs/sandbox-cost-benchmark.md`, then rebuild and redeploy the worker image.

Provider-only schedules can still be bootstrapped for debugging:

```sh
uv run python infra/windmill/bootstrap_provider_schedule.py --provider vast
uv run python infra/windmill/bootstrap_provider_schedule.py --provider lium
```

Run a manual smoke through the same VPC worker path:

```sh
uv run python infra/windmill/bootstrap_market_schedule.py \
  --run-now \
  --wait \
  --run-id market-stage1-smoke-YYYYMMDD
```

The success marker is a market-run manifest with provider checks, nonzero gold row counts, dashboard
output refs, and provider manifests with `publish_mode: kafka`.

## Smoke Command

Inside a VPC-connected worker image, this is the equivalent command:

```sh
gpu-prices ingest-vast
gpu-prices ingest-lium --size 200 --paginate --max-pages 10
gpu-prices ingest-rate-card --provider published_rate_cards
gpu-prices market-hourly
```

From your laptop, use the SSH tunnel and local token to prove the Stage 1 surface:

```sh
WINDMILL_BASE_URL=http://127.0.0.1:8081 uv run gpu-prices stage1-check
```

From the VPC worker, add the private Kafka check:

```sh
gpu-prices stage1-check --check-automq --require-ingest-env
```

The current dev worker runs with `DISABLE_NSJAIL=true` so it can use the baked project virtualenv
at `/opt/compute-bazaar`. Tighten that before production by moving the worker image to a registry
and using Windmill's normal sandbox image flow.
