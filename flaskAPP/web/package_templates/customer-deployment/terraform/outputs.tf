output "report_bucket_name" {
  description = "S3 bucket used for optimisation reports"
  value       = aws_s3_bucket.reports.bucket
}

output "runner_lambda_name" {
  description = "Name of the runner lambda"
  value       = aws_lambda_function.runner.function_name
}

output "enabled_services" {
  description = "Services enabled for this customer deployment"
  value       = var.enabled_services
}

output "eventbridge_schedule_name" {
  description = "EventBridge rule name for runner schedule"
  value       = aws_cloudwatch_event_rule.runner_schedule.name
}