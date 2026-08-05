variable "aws_region" {
  description = "AWS region where the dashboard S3 bucket lives."
  type        = string
}

variable "dashboard_bucket_name" {
  description = "Existing private S3 bucket that contains dashboard/compute-bazaar/*.json."
  type        = string
}

variable "dashboard_prefix" {
  description = "S3 prefix containing public-safe dashboard JSON files."
  type        = string
  default     = "dashboard/compute-bazaar"

  validation {
    condition     = length(trim(var.dashboard_prefix, "/")) > 0
    error_message = "dashboard_prefix must not be empty."
  }
}

variable "name" {
  description = "Short name used for CloudFront resources."
  type        = string
  default     = "compute-bazaar-public-feed"
}

variable "allowed_origins" {
  description = "Browser origins allowed to fetch the dashboard JSON."
  type        = list(string)
  default = [
    "https://www.adamsioud.com",
    "https://adamsioud.com",
    "http://127.0.0.1:8777",
    "http://127.0.0.1:8801",
  ]
}

variable "price_class" {
  description = "CloudFront price class. PriceClass_100 keeps the edge footprint modest."
  type        = string
  default     = "PriceClass_100"
}

variable "custom_domain_name" {
  description = "Branded hostname to request an ACM certificate for, such as bazaar.adamsioud.com."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition = (
      var.custom_domain_name == null
      || can(regex(
        "^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$",
        var.custom_domain_name,
      ))
    )
    error_message = "custom_domain_name must be null or a lowercase DNS hostname."
  }
}

variable "enable_custom_domain" {
  description = "Attach custom_domain_name to CloudFront after its ACM certificate is issued."
  type        = bool
  default     = false
}

variable "cloudfront_aliases" {
  description = "Advanced: externally managed CloudFront aliases used when enable_custom_domain is false."
  type        = list(string)
  default     = []
}

variable "acm_certificate_arn" {
  description = "Advanced: externally managed us-east-1 ACM certificate for cloudfront_aliases."
  type        = string
  default     = null
}

variable "manage_bucket_cors" {
  description = "Whether this stack should manage the bucket CORS configuration."
  type        = bool
  default     = true
}

variable "manage_bucket_policy" {
  description = "Whether this stack should own the entire bucket policy. Leave false if the bucket already has hand-managed policy statements."
  type        = bool
  default     = false
}
