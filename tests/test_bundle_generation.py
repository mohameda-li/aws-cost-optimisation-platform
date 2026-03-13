import json
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = PROJECT_ROOT / "flaskAPP" / "web"
if str(WEB_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_DIR))

import app as web_app


class TestBundleGeneration(unittest.TestCase):
    def test_bundle_contains_selected_services_only(self):
        sample = {
            "customer_id": "org_test",
            "company_name": "Northshore Retail Group",
            "aws_region": "eu-west-2",
            "report_bucket_name": "northshore-reports",
            "notification_email": "ops@example.com",
            "schedule_expression": "rate(7 days)",
            "s3_default_days_since_access": 60,
            "s3_target_buckets": ["a-bucket"],
            "enabled_service_codes": ["s3", "rds"],
            "services": {"s3": True, "rds": True, "ecs": False, "eks": False, "spot": False},
        }

        real_template = Path(web_app.app.root_path) / "package_templates" / "customer-deployment"

        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp) / "web"
            template_target = tmp_root / "package_templates" / "customer-deployment"
            shutil.copytree(real_template, template_target)

            with patch.object(web_app.app, "root_path", str(tmp_root)):
                bundle = web_app.create_customer_bundle(sample)

            bundle_dir = Path(bundle["bundle_dir"])
            self.assertTrue(bundle_dir.exists())
            self.assertTrue((bundle_dir / "lambdas" / "runner.zip").exists())
            self.assertTrue((bundle_dir / "lambdas" / "s3_optimiser.zip").exists())
            self.assertTrue((bundle_dir / "lambdas" / "rds_optimiser.zip").exists())
            self.assertFalse((bundle_dir / "lambdas" / "ecs_optimiser.zip").exists())
            self.assertTrue((bundle_dir / "data" / "s3" / "s3_pricing.csv").exists())
            self.assertTrue((bundle_dir / "data" / "rds" / "rds_pricing.csv").exists())
            self.assertFalse((bundle_dir / "data" / "ecs").exists())

            config = json.loads((bundle_dir / "config" / "customer_config.json").read_text(encoding="utf-8"))
            self.assertEqual(["s3", "rds"], config["enabled_services"])
            self.assertEqual(["html", "json"], config["reporting"]["report_formats"])

            with zipfile.ZipFile(bundle_dir / "lambdas" / "runner.zip") as runner_zip:
                names = set(runner_zip.namelist())
                self.assertIn("lambda_function.py", names)
                self.assertIn("s3/lambda_function.py", names)
                self.assertIn("rds/lambda_function.py", names)
                self.assertIn("data/s3/s3_pricing.csv", names)
                self.assertNotIn("ecs/lambda_function.py", names)


if __name__ == "__main__":
    unittest.main()
