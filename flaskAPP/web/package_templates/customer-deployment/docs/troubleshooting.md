Troubleshooting
===============

Terraform issues
----------------

- Check that AWS credentials are valid
- Confirm the selected AWS region is correct
- Re-run `terraform init` if providers are missing
- If `terraform apply` fails during the automatic initial report step, confirm the AWS CLI is installed locally and can run `aws lambda invoke`
- If `terraform apply` succeeds but you are unsure whether the first report ran, open `terraform/initial_report_response.json`
- If a later application from the same customer looks different, confirm you are deploying the correct bundle. Each application generates its own bundle and settings snapshot.

Email issues
------------

- Confirm `smtp_host`, `smtp_port`, `smtp_username`, `smtp_password`, `smtp_sender`, and `smtp_use_tls` are correct in `terraform.tfvars`
- If using Amazon SES SMTP, confirm the sender identity is verified and the SMTP credentials are valid
- If reports are generated in S3 but no email arrives, invoke the runner manually and inspect the returned JSON for `email_notification` or `email_notification_error`

Lambda issues
-------------

- Check CloudWatch logs for the runner and optimiser functions
- Confirm the required service package was included in the generated bundle
- Confirm the report bucket exists and is writable
- Check `terraform/initial_report_response.json` from the automatic first run
- If needed, invoke the runner manually and inspect the returned JSON body
- If the bundle downloads from the admin workspace but not the customer dashboard, check the application status. Rejected applications do not expose the bundle to the customer.

No findings in report
---------------------

- Verify the correct services were enabled in onboarding
- Verify target buckets or service filters were configured correctly
- Check whether the analysed account currently has matching AWS resources
- Zero findings with no runtime errors still indicates a successful deployment when the account has no matching resources

Customer/admin messaging
------------------------

- Customer-to-admin conversations are linked to each application separately.
- If an expected conversation does not appear, confirm you opened the correct application because messages are not shared across different applications from the same customer account.
