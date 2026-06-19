output "cloudfront_distribution_id" {
  description = "CloudFront distribution ID for invalidations."
  value       = aws_cloudfront_distribution.dashboard.id
}

output "cloudfront_domain_name" {
  description = "Default CloudFront domain."
  value       = aws_cloudfront_distribution.dashboard.domain_name
}

output "dashboard_data_base_url" {
  description = "Base URL for manifest.json, latest-index.json, and related dashboard snapshots."
  value       = "https://${aws_cloudfront_distribution.dashboard.domain_name}"
}

output "bucket_policy_json" {
  description = "Policy statement that grants CloudFront OAC read access to the dashboard prefix. Merge this manually if manage_bucket_policy is false."
  value       = data.aws_iam_policy_document.dashboard_cloudfront_read.json
}

output "s3_dashboard_prefix" {
  description = "Private S3 prefix mirrored by this CloudFront distribution."
  value       = "s3://${var.dashboard_bucket_name}/${local.dashboard_prefix}"
}
