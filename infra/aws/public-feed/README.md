# Public feed

This is the optional hosted public-feed deployment. The default CLI sync uses
the repository's `public-lake` GitHub Release and does not require this stack.

This Terraform stack serves files from the private S3 prefix
`dashboard/compute-bazaar/` through CloudFront and a configured hostname.

It configures CloudFront, S3 read access, CORS, security headers, the TLS
certificate, and extensionless publication URLs. It does not expose `raw/` or
the private market lake. The public `lake/` route is a sanitized copy written
under `dashboard/compute-bazaar/`.

## Setup

Keep deployment values outside Git:

```bash
mkdir -p .secrets
cp infra/aws/public-feed/terraform.tfvars.example .secrets/public-feed.tfvars

terraform -chdir=infra/aws/public-feed init
terraform -chdir=infra/aws/public-feed plan \
  -var-file=../../../.secrets/public-feed.tfvars
terraform -chdir=infra/aws/public-feed apply \
  -var-file=../../../.secrets/public-feed.tfvars
```

Terraform state is stored in the private S3 backend in `backend.tf`. Do not
commit `.terraform/`, plans, state copies, or real tfvars.

## Routes

Files such as `manifest.json` use a short cache. Publication files do not
change after they are written.

The CloudFront function maps:

```text
/publications/gpu-index/h100/1-day/REVISION
```

to the matching `.html` file in S3. It leaves JSON, images, explicit file
extensions, and other routes alone.

Get the public base URL with:

```bash
terraform -chdir=infra/aws/public-feed output -raw dashboard_data_base_url
```

Set `COMPUTE_BAZAAR_PUBLIC_BASE_URL` to that hostname when building publication
metadata.

Before applying, check that the bucket policy only grants CloudFront access to
the public prefix.
