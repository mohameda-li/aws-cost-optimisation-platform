Troubleshooting
===============

Terraform issues
----------------

- Check that AWS credentials are valid
- Confirm the selected AWS region is correct
- Re-run `terraform init` if providers are missing

Lambda issues
-------------

- Check CloudWatch logs for the runner and optimiser functions
- Confirm the required optimiser was included in the generated bundle
- Confirm the report bucket exists and is writable

No findings in report
---------------------

- Verify the correct services were enabled in onboarding
- Verify target buckets or service filters were configured correctly
- Check whether the analysed account currently has matching AWS resources
