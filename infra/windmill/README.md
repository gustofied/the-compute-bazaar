# Windmill

Windmill runs two scheduled Python jobs:

- `market_hourly.py` calls `run_market_hourly()`.
- `sandbox_benchmark_daily.py` imports new public StarSling results.

The market job pulls providers, writes Bronze and Silver, runs the DataFusion
SQL models, writes Gold, publishes JSON, and writes the market-run manifest.
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
  -L 8081:127.0.0.1:8081 \
  ec2-user@RUNTIME_HOST
```

- AutoMQ: `http://127.0.0.1:8080`
- Windmill: `http://127.0.0.1:8081`

Do not open ports 8080 or 8081 in the public security group.

## Worker image

Build from the repository root:

```bash
docker build \
  -f infra/windmill/self-host/Dockerfile.worker \
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
uv run python infra/windmill/bootstrap_sandbox_benchmark_schedule.py
```

The default six-field cron is hourly:

```text
0 0 * * * *
```

The StarSling job only reads results published in its public repository. It
does not run paid workloads. The hourly market job picks up new results.

Run the market job manually with:

```bash
uv run python infra/windmill/bootstrap_market_schedule.py \
  --run-now \
  --wait \
  --run-id market-manual-YYYYMMDD
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
curl -sS http://127.0.0.1:8081/api/health/status
```
