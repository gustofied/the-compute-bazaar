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
  value = (
    local.custom_domain_enabled
    ? "https://${local.custom_domain}"
    : "https://${aws_cloudfront_distribution.dashboard.domain_name}"
  )
}

output "custom_domain_certificate_arn" {
  description = "ACM certificate requested in us-east-1 for the branded hostname."
  value = (
    local.custom_domain_requested
    ? aws_acm_certificate.dashboard[0].arn
    : null
  )
}

output "custom_domain_certificate_status" {
  description = "Current ACM status. Add the validation CNAME while this is PENDING_VALIDATION."
  value = (
    local.custom_domain_requested
    ? aws_acm_certificate.dashboard[0].status
    : null
  )
}

output "custom_domain_validation_records" {
  description = "CNAME records to add at the external DNS provider for ACM validation."
  value = local.custom_domain_requested ? {
    for option in aws_acm_certificate.dashboard[0].domain_validation_options :
    option.domain_name => {
      name  = option.resource_record_name
      type  = option.resource_record_type
      value = option.resource_record_value
    }
  } : {}
}

output "custom_domain_cname_target" {
  description = "CNAME target to use after the certificate is issued and the alias is enabled."
  value       = aws_cloudfront_distribution.dashboard.domain_name
}

output "bucket_policy_json" {
  description = "Policy statement that grants CloudFront OAC read access to the dashboard prefix. Merge this manually if manage_bucket_policy is false."
  value       = data.aws_iam_policy_document.dashboard_cloudfront_read.json
}

output "s3_dashboard_prefix" {
  description = "Private S3 prefix mirrored by this CloudFront distribution."
  value       = "s3://${var.dashboard_bucket_name}/${local.dashboard_prefix}"
}
