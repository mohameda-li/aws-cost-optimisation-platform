import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = PROJECT_ROOT / "flaskAPP" / "web"
if str(WEB_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_DIR))

from web_common import build_customer_bundle_data, get_enabled_service_codes, slugify


class TestWebCommon(unittest.TestCase):
    def test_slugify_normalises_customer_names(self):
        self.assertEqual("northshore-retail-group", slugify(" Northshore Retail Group "))
        self.assertEqual("acme-co-2026", slugify("Acme & Co. 2026"))

    def test_get_enabled_service_codes_prefers_explicit_deduplicated_list(self):
        customer_data = {
            "enabled_service_codes": ["S3", "rds", "s3", "invalid", "", "EKS"],
            "services": {"spot": True},
        }
        self.assertEqual(["s3", "rds", "eks"], get_enabled_service_codes(customer_data))

    def test_get_enabled_service_codes_falls_back_to_service_flags(self):
        customer_data = {"services": {"s3": True, "rds": False, "eks": True, "spot": True}}
        self.assertEqual(["s3", "eks", "spot"], get_enabled_service_codes(customer_data))

    def test_build_customer_bundle_data_uses_report_email_and_defaults(self):
        data = {
            "organisation_id": 7,
            "organisation_name": "Northshore Retail Group",
            "aws_region": "",
            "contact_email": "owner@example.com",
            "report_frequency": "monthly",
        }

        payload = build_customer_bundle_data(
            data,
            ["s3", "rds"],
            {"report_email": "reports@example.com"},
        )

        self.assertEqual("org_7", payload["customer_id"])
        self.assertEqual("eu-west-2", payload["aws_region"])
        self.assertEqual("northshore-retail-group-finops-reports", payload["report_bucket_name"])
        self.assertEqual("reports@example.com", payload["notification_email"])
        self.assertEqual("rate(30 days)", payload["schedule_expression"])
        self.assertTrue(payload["services"]["s3"])
        self.assertTrue(payload["services"]["rds"])
        self.assertFalse(payload["services"]["spot"])


if __name__ == "__main__":
    unittest.main()
