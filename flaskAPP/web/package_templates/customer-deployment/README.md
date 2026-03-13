Customer Deployment Bundle
==========================

This bundle is generated for a specific customer deployment.

Contents
--------

- `terraform/` infrastructure definitions
- `lambdas/` packaged runner and selected optimiser Lambdas
- `config/` generated customer configuration
- `data/` pricing reference data for the selected services
- `docs/` deployment and troubleshooting notes

Deployment
----------

1. Open a terminal in `terraform/`
2. Run `terraform init`
3. Run `terraform apply`

The resources are deployed into the customer's AWS account.

Reports
-------

The platform generates HTML and JSON reports and stores them in the configured S3 bucket.
