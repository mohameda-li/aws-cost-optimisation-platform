Customer Deployment Bundle
==========================

This bundle contains everything needed to deploy your cost optimisation platform into your AWS account.

Contents
--------

- `terraform/` infrastructure definitions
- `lambdas/` packaged Lambda functions for the runner and selected services
- `config/` customer-specific configuration
- `data/` pricing reference data used during optimisation
- `docs/` deployment and troubleshooting notes

Deployment
----------

1. Open a terminal in `terraform/`
2. Run `terraform init`
3. Run `terraform apply`

The deployment creates the required resources in your AWS account.

Reports
-------

The platform generates HTML and JSON reports and stores them in your configured S3 bucket.
