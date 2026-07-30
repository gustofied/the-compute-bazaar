# Public Dashboard Infra

This stack publishes only the public-safe Compute Bazaar dashboard JSON:

```text
s3://YOUR_BUCKET/dashboard/compute-bazaar/*.json
  -> CloudFront Origin Access Control
  -> https://bazaar.adamsioud.com/*.json
```

It does not publish `raw/` or `lake/`. CloudFront uses `origin_path =
/dashboard/compute-bazaar`, so browser consumers fetch:

```text
https://DISTRIBUTION.cloudfront.net/manifest.json
https://DISTRIBUTION.cloudfront.net/latest-index.json
```

## Apply

Copy the example vars and fill in the bucket:

```sh
cd infra/aws/public-dashboard
cp terraform.tfvars.example terraform.tfvars
terraform init
terraform plan
terraform apply
```

Terraform state is stored in the private project bucket:

```text
s3://compute-bazaar-852794024525-eu-west-3-an/terraform/public-dashboard/terraform.tfstate
```

The backend uses S3 lockfiles, so re-run `terraform init` after cloning before planning or applying.

If `manage_bucket_policy = false`, Terraform will not replace the bucket policy.
Use the `bucket_policy_json` output and merge the statement into the existing
bucket policy, or set `manage_bucket_policy = true` if this stack should own the
whole bucket policy.

## Website Wiring

After apply, copy `dashboard_data_base_url` into the AdamSioud compute page:

```html
<div
  class="market-signal"
  data-market-signal
  data-market-data-base="https://DISTRIBUTION.cloudfront.net"
>
```

For local testing, the same page still works with the same-origin FastAPI proxy:

```text
http://127.0.0.1:8777/exemplars/compute-bazaar/
```

You can also override the data source without editing HTML:

```text
?data=https://DISTRIBUTION.cloudfront.net
```

## Cache

The cache policy is intentionally short while the hourly market feed is young:
60 seconds default TTL, 300 seconds max TTL. The market job overwrites stable
filenames such as `manifest.json` and `latest-index.json`, so short caching keeps
the public page fresh without requiring invalidations every hour.

## Branded Hostname

The custom hostname is activated in two phases because DNS is hosted outside
AWS. This keeps the existing CloudFront URL live while the certificate is
validated.

First request the certificate without changing the distribution:

```hcl
custom_domain_name   = "bazaar.adamsioud.com"
enable_custom_domain = false
```

```sh
terraform apply
terraform output -json custom_domain_validation_records
```

Add the returned CNAME at the DNS provider. ACM certificates used by
CloudFront must be issued in `us-east-1`; the stack configures that provider
automatically. Wait until:

```sh
terraform output -raw custom_domain_certificate_status
```

returns `ISSUED`. Then activate the alias:

```hcl
enable_custom_domain = true
```

Apply again and add the public DNS record:

```text
Host    bazaar
Type    CNAME
Value   terraform output -raw custom_domain_cname_target
```

After HTTPS resolves, use `dashboard_data_base_url` for the public article and
`COMPUTE_BAZAAR_PUBLIC_BASE_URL` for generated publication metadata. Keep the
CloudFront hostname as a fallback, not as the public sharing identity.
