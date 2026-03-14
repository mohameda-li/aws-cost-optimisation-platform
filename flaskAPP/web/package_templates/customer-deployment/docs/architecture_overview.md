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

How it works
------------

1. EventBridge triggers the runner on the configured schedule
2. The runner checks the selected AWS services
3. The optimisation functions estimate possible savings
4. The results are combined into a report
5. The report is uploaded to S3

Report formats
--------------

- HTML
- JSON
