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
  -t compute-bazaar-windmill-worker:YYYY-MM-DD-description \
  .
```

The `.dockerignore` file excludes `.env`, `.secrets`, local notes, data, and git metadata from the
build context.

For Windmill jobs, there are two good shapes:

1. For this dev EC2 stack, use a custom Windmill worker image with this package baked in. That lets
   `infra/windmill/market_hourly.py` run as a normal Windmill Python script.
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

On the EC2 host, the live files sit under `/opt/windmill`. Windmill and the AutoMQ environment
console are management surfaces, not public application endpoints. Open only SSH from the
laptop's current `/32`, then tunnel both localhost-bound services:

```sh
ssh -i .secrets/compute-bazaar-automq-runtime.pem \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -L 8081:127.0.0.1:8081 \
  -L 8080:127.0.0.1:8080 \
  ec2-user@HOST
```

Then open:

```text
Windmill: http://127.0.0.1:8081
AutoMQ:   http://127.0.0.1:8080
```

If the laptop is on mobile/5G, the public IP can drift and the security group will stop allowing
SSH. Refresh the current `/32` before opening the tunnel:

```sh
uv run python infra/aws/refresh_runtime_access.py --profile YOUR_AWS_PROFILE
```

Add `--dry-run` to preview, and add `--prune-stale` after this helper has created older managed
rules that should be removed.

Do not add ports 8080 or 8081 to the public security group. The tunnel encrypts management traffic;
direct HTTP access would expose console credentials and sessions in transit.

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
    -t compute-bazaar-windmill-worker:YYYY-MM-DD-description . &&
  sudo sed -i \
    "s|^WM_WORKER_IMAGE=.*|WM_WORKER_IMAGE=compute-bazaar-windmill-worker:YYYY-MM-DD-description|" \
    /opt/windmill/.env &&
  cd /opt/windmill &&
  sudo docker compose up -d --force-recreate windmill_worker
'
```

The dev runtime has a 20 GiB root volume and a persistent 4 GiB swapfile on the encrypted data
volume. The swapfile prevents the growing Gold history build from being killed under transient
memory pressure; it is a mitigation, not a substitute for bounding the history build or separating
the worker from the AutoMQ console. Repeated image builds can leave
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

The compose file pins tested upstream image digests and caps Docker JSON logs. Update image digests
intentionally, rebuild the custom worker against the same Windmill base, and run the health checks
before replacing the live containers.

## Required Environment

Set these as Windmill variables/secrets or worker environment variables:

```text
AWS_REGION=eu-west-3
AWS_DEFAULT_REGION=eu-west-3
COMPUTE_BAZAAR_RAW_ROOT=s3://YOUR_BUCKET/raw
COMPUTE_BAZAAR_LAKE_ROOT=s3://YOUR_BUCKET/lake
COMPUTE_BAZAAR_PUBLIC_BASE_URL=https://bazaar.adamsioud.com
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
ingest live compute-market APIs -> build GPU Gold -> export GPU history -> build StarSling measured-workload Gold -> export public JSON -> write market run manifest
```

The script imports `run_market_hourly()` from the installed project package and
calls it directly. Windmill schedules the run, the Python market service owns
the orchestration, and embedded DataFusion executes the maintained SQL models
that produce Gold.

`infra/windmill/sandbox_benchmark_daily.py` is a separate public-source
boundary. It:

1. polls the public StarSling repository for committed benchmark results;
2. ingests compatible evidence into immutable bronze and content-addressed
   silver without creating duplicate runtime observations;
3. leaves the next hourly market run to rebuild DataFusion gold and public
   JSON.

The daily schedule is enabled by default:

```sh
uv run python infra/windmill/bootstrap_sandbox_benchmark_schedule.py
```

Use `--disabled` only when intentionally pausing source ingestion. The job has
no provider credentials and never launches a paid sandbox. A source poll
changes workload history only when upstream publishes a new compatible run.

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
  "public_base_url": "$var:f/compute-bazaar/public_base_url",
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
Seven exact four-vCPU, 8 GiB VM offers are checked through official catalog
APIs inside every hourly run. Each check retains raw responses and appends one
normalized source snapshot, including unchanged prices. DataFusion emits a
gold point only when all seven vendor observations share that check time.
Akash is retained separately as a modeled request indication and never enters
the median. Managed-sandbox price evidence remains reviewed and versioned in
the project; the hourly job does not scrape those marketing pages. The public
StarSling benchmark repository and the first four unauthenticated VM source
schemas are checked separately each day by
`.github/workflows/sandbox-cost-sources.yml`. A failed check means new evidence
or schema drift needs review. After review, update canonical evidence with the
commit-pinned `sandbox-cost refresh-benchmark --update-evidence` command in
`docs/sandbox-cost-benchmark.md`, then rebuild and redeploy the worker image.

There are no separate provider schedules. Provider failures are isolated and
recorded inside the single market run, avoiding duplicate or competing hourly
generations.

Run a manual smoke through the same VPC worker path:

```sh
uv run python infra/windmill/bootstrap_market_schedule.py \
  --run-now \
  --wait \
  --run-id market-stage1-smoke-YYYYMMDD
```

The bootstrap client's synchronous wait allowance is 15 minutes. The broad
provider-to-publication cycle currently takes about six to seven minutes, so a
shorter client timeout can cancel an otherwise healthy Windmill job when the
HTTP connection closes. Scheduled runs and asynchronous `--run-now` submissions
do not depend on an open client connection.

The success marker is a market-run manifest with provider checks, nonzero gold row counts, dashboard
output refs, and provider manifests with `publish_mode: kafka`.

## Verification

Run the maintained hermetic tests locally, then use the bootstrap script's
`--run-now --wait` path for an end-to-end check through the VPC worker. A
successful result includes provider checks, nonzero Gold row counts, public
output references, and a market-run manifest.

The current dev worker runs with `DISABLE_NSJAIL=true` so it can use the baked project virtualenv
at `/opt/compute-bazaar`. Tighten that before production by moving the worker image to a registry
and using Windmill's normal sandbox image flow.
