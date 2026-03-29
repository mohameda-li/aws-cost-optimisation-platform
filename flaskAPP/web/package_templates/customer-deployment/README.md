Customer Deployment Bundle
==========================

This bundle contains everything needed to deploy your cost optimisation platform into your AWS account.

Contents
--------

- `terraform/` infrastructure definitions
- `lambdas/` packaged Lambda functions for the runner and selected services
- `config/` customer-specific configuration
- `docs/` deployment and troubleshooting notes

Deployment
----------

1. Open a terminal in `terraform/`
2. Run `terraform init`
3. Run `terraform apply`
4. Terraform will trigger one initial report automatically after the deployment completes
5. Future reports continue on the configured schedule

The deployment creates the required resources in your AWS account.

Simple validation after deploy
------------------------------

After `terraform apply`, check these three things:

1. `initial_report_response.json` exists in `terraform/`
2. the report bucket contains a new `.html` and `.json` file
3. the configured contact email receives the report notification

If all three happen, the deployment is working correctly.

Reference pricing data for the enabled services is bundled inside the packaged Lambda ZIPs in `lambdas/`, so there is no separate top-level `data/` directory in the generated bundle.

The generated Terraform and Lambda packages already include the required configuration for supported services. Customers do not need to add manual Lambda environment variables such as `AWS_REGION` or `ECS_CLUSTER`.

Email delivery
--------------

Scheduled report emails are sent directly using SMTP rather than AWS SNS email subscriptions.

Before deploying, review the SMTP values in `terraform/terraform.tfvars`:

- `smtp_host`
- `smtp_port`
- `smtp_username`
- `smtp_password`
- `smtp_sender`
- `smtp_use_tls`

If you are using Amazon SES SMTP, the host will usually look like `email-smtp.<region>.amazonaws.com`.

Reports
-------

The platform generates HTML and JSON reports and stores them in your configured S3 bucket under `reports/<customer>/<run_id>`.

By default, Terraform also triggers one initial report immediately after `terraform apply` so customers do not need to wait for the first scheduled run.

Debugging
---------

If the initial report does not appear:

- open `terraform/initial_report_response.json`
- check the report bucket in AWS S3
- check the runner Lambda logs in CloudWatch
- confirm the SMTP settings in `terraform/terraform.tfvars` if the report email does not arrive
