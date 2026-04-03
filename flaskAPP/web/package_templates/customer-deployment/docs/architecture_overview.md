Architecture Overview
=====================

This deployment contains a serverless AWS cost optimisation workflow that runs inside your AWS account.

Components
----------

- Runner Lambda orchestrator
- Selected optimiser Lambdas
- IAM execution role
- EventBridge schedule
- CloudWatch log groups
- S3 bucket for generated reports
- SMTP-configured email delivery for report notifications

How it works
------------

1. Terraform deploys the runner, selected optimiser functions, IAM role, schedule, and report bucket
2. Terraform triggers one initial report run after deployment
3. EventBridge then continues to trigger the runner on the configured schedule
4. The runner checks the selected AWS services
5. The optimisation functions estimate possible savings
6. The results are combined into a report
7. The report is uploaded to S3
8. If SMTP is configured, the runner sends a report notification email

Report formats
--------------

- HTML
- JSON
