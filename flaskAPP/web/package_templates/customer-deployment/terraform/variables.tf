variable "aws_region" {
  description = "AWS region for deployment"
  type        = string
}

variable "customer_id" {
  description = "Unique customer identifier"
  type        = string
}

variable "company_name" {
  description = "Customer company name"
  type        = string
}

variable "report_bucket_name" {
  description = "S3 bucket name for generated reports"
  type        = string
}

variable "notification_email" {
  description = "Email address for report notifications"
  type        = string
}

variable "schedule_expression" {
  description = "EventBridge schedule expression"
  type        = string
}

variable "s3_default_days_since_access" {
  description = "Default inactivity threshold for S3 optimisation"
  type        = number
}

variable "s3_target_buckets" {
  description = "Comma-separated S3 target bucket names"
  type        = string
}

variable "enabled_services" {
  description = "List of enabled optimiser services"
  type        = list(string)
}