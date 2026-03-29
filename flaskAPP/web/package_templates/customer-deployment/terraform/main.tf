terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

locals {
  common_prefix = "finops-${var.customer_id}"
}

resource "aws_s3_bucket" "reports" {
  bucket = var.report_bucket_name
}

resource "aws_cloudwatch_log_group" "runner_logs" {
  name              = "/aws/lambda/${local.common_prefix}-runner"
  retention_in_days = 14
}

resource "aws_lambda_function" "runner" {
  function_name = "${local.common_prefix}-runner"
  role          = aws_iam_role.lambda_exec_role.arn
  handler       = "lambda_function.handler"
  runtime       = "python3.11"
  filename      = "${path.module}/../lambdas/runner.zip"
  timeout       = 60

  environment {
    variables = {
      CUSTOMER_ID                  = var.customer_id
      COMPANY_NAME                 = var.company_name
      REPORT_BUCKET_NAME           = var.report_bucket_name
      NOTIFICATION_EMAIL           = var.notification_email
      ENABLED_SERVICES             = join(",", var.enabled_services)
      S3_DEFAULT_DAYS_SINCE_ACCESS = tostring(var.s3_default_days_since_access)
      S3_TARGET_BUCKETS            = var.s3_target_buckets
      SMTP_HOST                    = var.smtp_host
      SMTP_PORT                    = tostring(var.smtp_port)
      SMTP_USERNAME                = var.smtp_username
      SMTP_PASSWORD                = var.smtp_password
      SMTP_SENDER                  = var.smtp_sender
      SMTP_USE_TLS                 = tostring(var.smtp_use_tls)
    }
  }

  depends_on = [
    aws_iam_role_policy_attachment.lambda_basic,
    aws_iam_role_policy.lambda_custom_policy
  ]
}

resource "aws_lambda_function" "s3_optimiser" {
  count         = contains(var.enabled_services, "s3") ? 1 : 0
  function_name = "${local.common_prefix}-s3-optimiser"
  role          = aws_iam_role.lambda_exec_role.arn
  handler       = "lambda_function.handler"
  runtime       = "python3.11"
  filename      = "${path.module}/../lambdas/s3_optimiser.zip"
  timeout       = 60

  depends_on = [
    aws_iam_role_policy_attachment.lambda_basic,
    aws_iam_role_policy.lambda_custom_policy
  ]
}

resource "aws_lambda_function" "rds_optimiser" {
  count         = contains(var.enabled_services, "rds") ? 1 : 0
  function_name = "${local.common_prefix}-rds-optimiser"
  role          = aws_iam_role.lambda_exec_role.arn
  handler       = "lambda_function.handler"
  runtime       = "python3.11"
  filename      = "${path.module}/../lambdas/rds_optimiser.zip"
  timeout       = 60

  depends_on = [
    aws_iam_role_policy_attachment.lambda_basic,
    aws_iam_role_policy.lambda_custom_policy
  ]
}

resource "aws_lambda_function" "ecs_optimiser" {
  count         = contains(var.enabled_services, "ecs") ? 1 : 0
  function_name = "${local.common_prefix}-ecs-optimiser"
  role          = aws_iam_role.lambda_exec_role.arn
  handler       = "lambda_function.handler"
  runtime       = "python3.11"
  filename      = "${path.module}/../lambdas/ecs_optimiser.zip"
  timeout       = 60

  depends_on = [
    aws_iam_role_policy_attachment.lambda_basic,
    aws_iam_role_policy.lambda_custom_policy
  ]
}

resource "aws_lambda_function" "eks_optimiser" {
  count         = contains(var.enabled_services, "eks") ? 1 : 0
  function_name = "${local.common_prefix}-eks-optimiser"
  role          = aws_iam_role.lambda_exec_role.arn
  handler       = "lambda_function.handler"
  runtime       = "python3.11"
  filename      = "${path.module}/../lambdas/eks_optimiser.zip"
  timeout       = 60

  depends_on = [
    aws_iam_role_policy_attachment.lambda_basic,
    aws_iam_role_policy.lambda_custom_policy
  ]
}

resource "aws_lambda_function" "spot_optimiser" {
  count         = contains(var.enabled_services, "spot") ? 1 : 0
  function_name = "${local.common_prefix}-spot-optimiser"
  role          = aws_iam_role.lambda_exec_role.arn
  handler       = "lambda_function.handler"
  runtime       = "python3.11"
  filename      = "${path.module}/../lambdas/spot_optimiser.zip"
  timeout       = 60

  depends_on = [
    aws_iam_role_policy_attachment.lambda_basic,
    aws_iam_role_policy.lambda_custom_policy
  ]
}

resource "aws_cloudwatch_event_rule" "runner_schedule" {
  name                = "${local.common_prefix}-schedule"
  schedule_expression = var.schedule_expression
}

resource "aws_cloudwatch_event_target" "runner_target" {
  rule      = aws_cloudwatch_event_rule.runner_schedule.name
  target_id = "RunnerLambda"
  arn       = aws_lambda_function.runner.arn
}

resource "aws_lambda_permission" "allow_eventbridge" {
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.runner.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.runner_schedule.arn
}

# Trigger one report immediately after deployment so customers can confirm
# the platform is working without waiting for the first scheduled run.
resource "terraform_data" "initial_report_run" {
  count = var.run_initial_report_on_apply ? 1 : 0

  triggers_replace = {
    runner_name = aws_lambda_function.runner.function_name
    runner_arn  = aws_lambda_function.runner.arn
  }

  provisioner "local-exec" {
    # Terraform writes the Lambda response to a local file that can be opened
    # if the initial run needs debugging after apply completes.
    command = "aws lambda invoke --function-name ${aws_lambda_function.runner.function_name} --region ${var.aws_region} ${path.module}/initial_report_response.json >/dev/null"
  }

  depends_on = [
    aws_lambda_function.runner,
    aws_cloudwatch_event_target.runner_target,
    aws_lambda_permission.allow_eventbridge,
  ]
}
