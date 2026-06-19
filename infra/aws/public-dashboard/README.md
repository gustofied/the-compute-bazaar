# Public Dashboard Infra

This stack publishes only the public-safe Compute Bazaar dashboard JSON:

```text
s3://YOUR_BUCKET/dashboard/compute-bazaar/*.json
  -> CloudFront Origin Access Control
  -> https://DISTRIBUTION.cloudfront.net/*.json
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
http://127.0.0.1:8777/exemplars/compute/feeling_the_compute.html
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
