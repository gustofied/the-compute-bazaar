# Infrastructure and Security

This note records the live dev architecture audited on 5 August 2026. It
separates verified controls from production work that remains. The stack is
suitable for a private development market feed; it is not yet a hardened
multi-tenant service.

## Trust Boundaries

```text
public provider APIs
  -> Windmill worker in the AWS VPC
  -> AutoMQ private Kafka endpoint (transient event tape)
  -> private S3 bronze, silver, gold, and run manifests (durable market memory)
  -> public-safe S3 prefix
  -> CloudFront / bazaar.adamsioud.com
  -> article, publication cards, and public JSON clients
```

Windmill orchestrates the hourly observation cycle. AutoMQ distributes events
but is not the source of truth. S3 is the durable record. DataFusion reads
Parquet from S3 and builds Gold products. The browser receives only selected
publication JSON/HTML through CloudFront; it never receives AWS, Kafka,
Windmill, or provider credentials.

## Verified Controls

- The S3 bucket blocks public access, has versioning enabled, and encrypts new
  objects with AES-256.
- CloudFront uses Origin Access Control and can read only
  `dashboard/compute-bazaar/*`. Direct S3 reads and CloudFront requests for
  `raw/` fail.
- Browser CORS is allowlisted and CloudFront redirects HTTP to HTTPS. Terraform
  is prepared to add HSTS, MIME sniffing protection, same-origin framing, and a
  strict-origin referrer policy, but the daily IAM profile cannot plan or apply
  that change; treat those headers as pending admin deployment.
- AutoMQ brokers have private addresses and private DNS. Kafka client ports are
  restricted to the VPC CIDR; no broker client port accepts `0.0.0.0/0`.
- The runtime host accepts SSH only from a managed laptop `/32`. Windmill binds
  to host localhost. Windmill and AutoMQ consoles are accessed through an
  encrypted SSH tunnel.
- EC2 Instance Metadata Service v2 is required. Runtime EBS volumes are
  encrypted.
- Local `.env`, `.secrets/`, private keys, Terraform state, and downloaded
  `data/` are ignored by Git. Runtime secret and compose files are mode `0600`.
- The Windmill schedule is hourly. After adding persistent swap, a complete run
  succeeded with all provider, Gold, dashboard, VM, and sandbox checks passing.

## Accepted Dev Exceptions

- AutoMQ currently uses `SASL_PLAINTEXT` inside the VPC. SCRAM authenticates
  clients, but broker traffic and credentials are not encrypted on the wire.
  Use `SASL_SSL` before crossing a private network boundary or treating this as
  production.
- AutoMQ broker EBS volumes are unencrypted because the instance was created
  with data encryption disabled. Changing this requires a planned cluster
  migration or recreation.
- The Windmill worker is privileged for PID namespace isolation and has NSJAIL
  disabled. It is appropriate only for trusted first-party jobs. Do not let
  untrusted users submit scripts.
- AutoMQ, Windmill, Postgres, and the hourly DataFusion build share an 8 GiB
  runtime host. A 4 GiB encrypted swapfile prevents immediate OOM kills, but
  the durable fix is to bound history memory use or move the worker to separate
  compute. The 20 GiB root disk should be expanded before more images are built
  on-host.
- The public stack has no verified WAF or access logging. Those are useful when
  the public surface becomes operationally important, but they are not
  substitutes for keeping private prefixes inaccessible.

## Not Verified by the Daily IAM Profile

The `compute-bazaar` AWS profile deliberately cannot enumerate IAM policies or
read several account-level and bucket-policy controls. This reduces the damage
of a leaked daily credential, but an admin audit must still verify:

- the exact runtime and AutoMQ instance-role policies;
- S3 server access or CloudTrail data-event logging;
- CloudFront standard or real-time logging;
- the pending CloudFront response-header policy deployment;
- account root MFA, alternate contacts, budgets, and billing alerts;
- access-key age and whether the daily IAM user can be replaced with IAM
  Identity Center.

Do not broaden the daily profile merely to make an audit command pass. Export
these configurations from an admin session or perform a separate read-only
account audit.

## Operator Access

Refresh the laptop's SSH rule, pruning managed stale addresses:

```sh
uv run python infra/aws/refresh_runtime_access.py \
  --profile compute-bazaar \
  --security-group-id YOUR_SECURITY_GROUP_ID \
  --prune-stale
```

Open one tunnel for both private management surfaces:

```sh
ssh -i .secrets/compute-bazaar-automq-runtime.pem \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -L 8080:127.0.0.1:8080 \
  -L 8081:127.0.0.1:8081 \
  ec2-user@RUNTIME_HOST
```

Then use `http://127.0.0.1:8080` for AutoMQ and
`http://127.0.0.1:8081` for Windmill. Never place either console URL or its
credentials in public frontend code.

## Next Security Work

1. Optimize cumulative Gold history construction or move Windmill to separate
   16 GiB compute.
2. Expand the runtime root disk and retain Docker log rotation and image
   cleanup.
3. Move Kafka to SASL over TLS and recreate encrypted broker storage when the
   dev cluster is replaced.
4. Pin and periodically review all container digests; keep provider and Kafka
   secrets in Windmill.
5. Run the admin-only IAM, logging, root-account, and billing audit before
   calling the stack production.
