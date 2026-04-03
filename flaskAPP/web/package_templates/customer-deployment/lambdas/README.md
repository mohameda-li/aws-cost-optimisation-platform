Lambda Packages
===============

This folder contains the packaged AWS Lambda functions needed for your deployment.

What is included
----------------

- `runner.zip`, which coordinates the optimisation run
- the optimiser packages for the AWS services selected during onboarding
- the configuration already needed for the initial post-deploy run and scheduled report generation

You do not need to edit these files manually.

Terraform uses the packages in this folder during deployment.
