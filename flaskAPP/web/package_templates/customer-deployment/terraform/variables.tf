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
  description = "Comma-separated email addresses for report notifications"
  type        = string
}

variable "smtp_host" {
  description = "SMTP host for direct report emails"
  type        = string
}

variable "smtp_port" {
  description = "SMTP port for direct report emails"
  type        = number
}

variable "smtp_username" {
  description = "SMTP username for direct report emails"
  type        = string
  sensitive   = true
}

variable "smtp_password" {
  description = "SMTP password for direct report emails"
  type        = string
  sensitive   = true
}

variable "smtp_sender" {
  description = "From address used for direct report emails"
  type        = string
}

variable "smtp_use_tls" {
  description = "Whether SMTP delivery should use TLS"
  type        = bool
}

variable "run_initial_report_on_apply" {
  description = "Whether Terraform should trigger an initial report run immediately after deployment"
  type        = bool
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
