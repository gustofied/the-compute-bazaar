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
  default     = "compute-bazaar-dashboard"
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

variable "cloudfront_aliases" {
  description = "Optional custom domains for the distribution, for example data.adamsioud.com."
  type        = list(string)
  default     = []
}

variable "acm_certificate_arn" {
  description = "ACM certificate ARN in us-east-1 when cloudfront_aliases is non-empty."
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
