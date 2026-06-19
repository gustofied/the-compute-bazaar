provider "aws" {
  region = var.aws_region
}

locals {
  dashboard_prefix = trimsuffix(trimprefix(var.dashboard_prefix, "/"), "/")
  origin_id        = "${var.name}-s3-origin"
}

check "custom_domain_certificate" {
  assert {
    condition = (
      length(var.cloudfront_aliases) == 0
      || (var.acm_certificate_arn != null && var.acm_certificate_arn != "")
    )
    error_message = "acm_certificate_arn is required when cloudfront_aliases is non-empty."
  }
}

data "aws_s3_bucket" "dashboard" {
  bucket = var.dashboard_bucket_name
}

resource "aws_cloudfront_origin_access_control" "dashboard" {
  name                              = "${var.name}-oac"
  description                       = "Read Compute Bazaar public dashboard JSON from S3"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_cache_policy" "dashboard_json" {
  name        = "${var.name}-short-json-cache"
  comment     = "Short cache for hourly Compute Bazaar JSON snapshots"
  default_ttl = 60
  max_ttl     = 300
  min_ttl     = 0

  parameters_in_cache_key_and_forwarded_to_origin {
    cookies_config {
      cookie_behavior = "none"
    }

    headers_config {
      header_behavior = "whitelist"

      headers {
        items = ["Origin"]
      }
    }

    query_strings_config {
      query_string_behavior = "none"
    }

    enable_accept_encoding_brotli = true
    enable_accept_encoding_gzip   = true
  }
}

resource "aws_cloudfront_response_headers_policy" "dashboard_cors" {
  name    = "${var.name}-cors"
  comment = "CORS for public-safe Compute Bazaar dashboard JSON"

  cors_config {
    access_control_allow_credentials = false
    access_control_max_age_sec       = 300
    origin_override                  = true

    access_control_allow_headers {
      items = ["*"]
    }

    access_control_allow_methods {
      items = ["GET", "HEAD", "OPTIONS"]
    }

    access_control_allow_origins {
      items = var.allowed_origins
    }

    access_control_expose_headers {
      items = ["ETag"]
    }
  }
}

resource "aws_cloudfront_distribution" "dashboard" {
  enabled         = true
  is_ipv6_enabled = true
  comment         = "Compute Bazaar public-safe dashboard JSON"
  aliases         = var.cloudfront_aliases
  price_class     = var.price_class

  origin {
    domain_name              = data.aws_s3_bucket.dashboard.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.dashboard.id
    origin_id                = local.origin_id
    origin_path              = "/${local.dashboard_prefix}"
  }

  default_cache_behavior {
    allowed_methods            = ["GET", "HEAD", "OPTIONS"]
    cached_methods             = ["GET", "HEAD"]
    cache_policy_id            = aws_cloudfront_cache_policy.dashboard_json.id
    compress                   = true
    response_headers_policy_id = aws_cloudfront_response_headers_policy.dashboard_cors.id
    target_origin_id           = local.origin_id
    viewer_protocol_policy     = "redirect-to-https"
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    acm_certificate_arn            = length(var.cloudfront_aliases) > 0 ? var.acm_certificate_arn : null
    cloudfront_default_certificate = length(var.cloudfront_aliases) == 0
    minimum_protocol_version       = "TLSv1.2_2021"
    ssl_support_method             = length(var.cloudfront_aliases) > 0 ? "sni-only" : null
  }
}

resource "aws_s3_bucket_cors_configuration" "dashboard" {
  count  = var.manage_bucket_cors ? 1 : 0
  bucket = data.aws_s3_bucket.dashboard.id

  cors_rule {
    allowed_headers = ["*"]
    allowed_methods = ["GET", "HEAD"]
    allowed_origins = var.allowed_origins
    expose_headers  = ["ETag"]
    max_age_seconds = 300
  }
}

data "aws_iam_policy_document" "dashboard_cloudfront_read" {
  statement {
    sid     = "AllowCloudFrontReadDashboardSnapshots"
    effect  = "Allow"
    actions = ["s3:GetObject"]

    resources = [
      "arn:aws:s3:::${var.dashboard_bucket_name}/${local.dashboard_prefix}/*",
    ]

    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values = [
        aws_cloudfront_distribution.dashboard.arn,
      ]
    }
  }
}

resource "aws_s3_bucket_policy" "dashboard_cloudfront_read" {
  count  = var.manage_bucket_policy ? 1 : 0
  bucket = data.aws_s3_bucket.dashboard.id
  policy = data.aws_iam_policy_document.dashboard_cloudfront_read.json
}
