Deployment Steps
================

Prerequisites
-------------

- AWS credentials configured locally
- Terraform installed

Deploy
------

```bash
cd terraform
terraform init
terraform apply
```

Review
------

Before applying, review:

- AWS region
- enabled services
- report bucket name
- schedule expression

If these values already match your requirements, you can continue without making changes.

After deployment
----------------

The platform runs automatically on the configured schedule and uploads reports to S3.
