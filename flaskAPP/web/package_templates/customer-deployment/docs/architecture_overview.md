Architecture Overview
=====================

This deployment contains a serverless AWS cost optimisation workflow.

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
2. The runner loads the enabled services
3. The selected optimisers analyse usage and estimate savings
4. The runner aggregates the results
5. Reports are generated and uploaded to S3

Report formats
--------------

- HTML
- JSON
