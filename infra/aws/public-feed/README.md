# Legacy AWS public feed

> The CloudFront distribution and S3 bucket described here were deleted on
> August 21, 2026. The current public feed is deployed with GitHub Actions and
> GitHub Pages; see `infra/github-pages/README.md`.

The public lake contains sanitized Silver and Gold outputs. Its rolling GitHub
Release is downloaded by `compute-bazaar data sync`.

This Terraform stack serves publications and the public `lake/` route from the
private S3 prefix `dashboard/compute-bazaar/` through CloudFront. It configures
S3 access, CORS, security headers, TLS, and extensionless publication URLs.
Bronze and the private market lake remain private.

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

`manifest.json` uses a short cache. Revisioned publication files are immutable.

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
