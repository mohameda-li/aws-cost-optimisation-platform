Deployment Steps
================

Prerequisites
-------------

- AWS credentials locally
- Terraform installed

Deploy
------

```bash
cd terraform
terraform init
terraform apply
```

By default, `terraform apply` now triggers one initial report automatically after the infrastructure is created.

If you want to run an extra manual check as well:

```bash
aws lambda invoke \
  --function-name <runner_lambda_name> \
  --region <aws_region> \
  response.json
cat response.json
```

Review
------

Before applying, review:

- AWS region
- enabled services
- report bucket name
- schedule expression
- notification email
- SMTP/SES SMTP settings

If these values already match your requirements, you can continue without making changes.

After deployment
----------------

The platform generates one initial report immediately after deployment, then continues on the configured schedule and uploads reports to S3.
If SMTP is configured, the runner also sends a direct report notification email to the configured report recipients.

Validation checklist
--------------------

- Confirm `terraform apply` completes successfully
- Confirm the initial report run completes successfully
- Open `initial_report_response.json` in the `terraform/` folder and confirm the response is successful
- Confirm the runner Lambda exists in AWS
- Confirm the report bucket exists in AWS
- Check the report bucket for new `.html` and `.json` report files
- Confirm the report notification email arrives if SMTP is configured

Notes
-----

- If the selected AWS account does not currently contain matching resources, services may return zero findings. This is expected and still confirms that the deployment is working correctly.
- The deployment bundle already packages the pricing reference files inside the Lambda ZIPs. No extra customer-side data folder is required.
