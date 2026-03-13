import importlib
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNNER_DIR = PROJECT_ROOT / "src" / "runner"
if str(RUNNER_DIR) not in sys.path:
    sys.path.insert(0, str(RUNNER_DIR))

if "boto3" not in sys.modules:
    sys.modules["boto3"] = types.SimpleNamespace(client=lambda *args, **kwargs: object())

runner = importlib.import_module("lambda_function")
report_generator = importlib.import_module("report_generator")


class TestRunnerHelpers(unittest.TestCase):
    def test_aggregate_totals(self):
        totals = runner._aggregate_totals(
            {
                "s3": {"baseline_monthly_cost": 10, "optimised_monthly_cost": 6, "total_monthly_savings": 4},
                "rds": {"baseline_monthly_cost": 20, "optimised_monthly_cost": 15, "total_monthly_savings": 5},
            }
        )
        self.assertEqual(
            {
                "baseline_monthly_cost": 30.0,
                "optimised_monthly_cost": 21.0,
                "total_monthly_savings": 9.0,
            },
            totals,
        )

    def test_top_actions_orders_by_savings(self):
        top_actions = runner._top_actions(
            {
                "s3": {
                    "recommendations": [
                        {"resource_id": "bucket-a", "action": "move", "estimated_monthly_savings": 3.0},
                        {"resource_id": "bucket-b", "action": "move", "estimated_monthly_savings": 9.0},
                    ]
                }
            },
            limit=1,
        )
        self.assertEqual(1, len(top_actions))
        self.assertEqual("bucket-b", top_actions[0]["resource_id"])

    def test_normalise_payload_rounds_money_fields(self):
        payload = runner._normalise_payload(
            {"total_monthly_savings": 3.456, "nested": [{"baseline_monthly_cost": "2.999"}]}
        )
        self.assertEqual(3.46, payload["total_monthly_savings"])
        self.assertEqual(3.0, payload["nested"][0]["baseline_monthly_cost"])

    def test_get_enabled_services_from_env_deduplicates(self):
        import os

        previous = os.environ.get("ENABLED_SERVICES")
        os.environ["ENABLED_SERVICES"] = "s3, rds, s3, EKS"
        try:
            self.assertEqual(["s3", "rds", "eks"], runner._get_enabled_services_from_env())
        finally:
            if previous is None:
                os.environ.pop("ENABLED_SERVICES", None)
            else:
                os.environ["ENABLED_SERVICES"] = previous

    def test_safe_call_returns_error_payload_on_exception(self):
        result = runner._safe_call("s3", lambda *_: (_ for _ in ()).throw(RuntimeError("boom")), {}, None)
        self.assertEqual("error", result["status"])
        self.assertEqual("s3", result["payload"]["service"])
        self.assertEqual(0.0, result["payload"]["total_monthly_savings"])

    def test_handler_builds_reports_and_s3_keys(self):
        import os
        from unittest.mock import patch

        previous_enabled = os.environ.get("ENABLED_SERVICES")
        previous_bucket = os.environ.get("REPORT_BUCKET_NAME")
        previous_region = os.environ.get("AWS_REGION")
        os.environ["ENABLED_SERVICES"] = "s3,rds"
        os.environ["REPORT_BUCKET_NAME"] = "reports-bucket"
        os.environ["AWS_REGION"] = "eu-west-2"

        class FakeS3Client:
            def __init__(self):
                self.uploads = []

            def upload_file(self, src, bucket, key, ExtraArgs=None):
                self.uploads.append((src, bucket, key, ExtraArgs))

        fake_s3 = FakeS3Client()

        def fake_generate_report_files(payload, output_dir, filename_prefix):
            html_path = output_dir / f"{filename_prefix}.html"
            json_path = output_dir / f"{filename_prefix}.json"
            html_path.parent.mkdir(parents=True, exist_ok=True)
            html_path.write_text("<html></html>", encoding="utf-8")
            json_path.write_text(json.dumps(payload), encoding="utf-8")
            return html_path, json_path

        handlers = {
            "s3": lambda event, context: {
                "statusCode": 200,
                "body": json.dumps(
                    {
                        "service": "s3",
                        "recommendations": [{"bucket": "a", "recommended_storage_class": "GLACIER"}],
                        "savings": {
                            "baseline_monthly_cost": 10,
                            "optimised_monthly_cost": 4,
                            "total_monthly_savings": 6,
                        },
                        "per_resource_costs": {
                            "a": {
                                "baseline_monthly_cost": 10,
                                "optimised_monthly_cost": 4,
                                "total_monthly_savings": 6,
                            }
                        },
                    }
                ),
            },
            "rds": lambda event, context: {
                "statusCode": 200,
                "body": json.dumps(
                    {
                        "service": "rds",
                        "baseline_monthly_cost": 20,
                        "optimised_monthly_cost": 10,
                        "total_monthly_savings": 10,
                        "recommendations": [{"db_instance": "db1", "recommended_action": "STOP"}],
                        "per_resource_costs": {
                            "db1": {
                                "baseline_monthly_cost": 20,
                                "optimised_monthly_cost": 10,
                                "total_monthly_savings": 10,
                            }
                        },
                    }
                ),
            },
        }

        try:
            with patch.object(runner, "_load_service_handler", side_effect=lambda name: handlers[name]), patch.object(
                runner, "generate_report_files", side_effect=fake_generate_report_files
            ), patch.object(runner.boto3, "client", return_value=fake_s3):
                response = runner.handler({"customer": "acme"}, None)

            body = json.loads(response["body"])
            self.assertEqual(200, response["statusCode"])
            self.assertEqual(16.0, body["totals"]["total_monthly_savings"])
            self.assertFalse(body["summary"]["partial_run"])
            self.assertIn("s3_keys", body["report_files"])
            self.assertEqual(2, len(fake_s3.uploads))
        finally:
            if previous_enabled is None:
                os.environ.pop("ENABLED_SERVICES", None)
            else:
                os.environ["ENABLED_SERVICES"] = previous_enabled
            if previous_bucket is None:
                os.environ.pop("REPORT_BUCKET_NAME", None)
            else:
                os.environ["REPORT_BUCKET_NAME"] = previous_bucket
            if previous_region is None:
                os.environ.pop("AWS_REGION", None)
            else:
                os.environ["AWS_REGION"] = previous_region

    def test_handler_records_partial_run_when_service_load_fails(self):
        import os
        from unittest.mock import patch

        previous_enabled = os.environ.get("ENABLED_SERVICES")
        os.environ["ENABLED_SERVICES"] = "s3"

        def fake_generate_report_files(payload, output_dir, filename_prefix):
            html_path = output_dir / f"{filename_prefix}.html"
            json_path = output_dir / f"{filename_prefix}.json"
            html_path.parent.mkdir(parents=True, exist_ok=True)
            html_path.write_text("<html></html>", encoding="utf-8")
            json_path.write_text(json.dumps(payload), encoding="utf-8")
            return html_path, json_path

        try:
            with patch.object(runner, "_load_service_handler", side_effect=ValueError("missing")), patch.object(
                runner, "generate_report_files", side_effect=fake_generate_report_files
            ):
                response = runner.handler({"customer": "acme"}, None)
            body = json.loads(response["body"])
            self.assertTrue(body["summary"]["partial_run"])
            self.assertEqual("error", body["service_status"]["s3"])
        finally:
            if previous_enabled is None:
                os.environ.pop("ENABLED_SERVICES", None)
            else:
                os.environ["ENABLED_SERVICES"] = previous_enabled


class TestReportGeneration(unittest.TestCase):
    def test_generate_report_files_outputs_html_and_json(self):
        payload = {
            "customer": "Test Org",
            "run_id": "run-123",
            "timestamp": "2026-03-13T10:00:00+00:00",
            "summary": {"savings_percent": 25, "top_actions": []},
            "totals": {
                "baseline_monthly_cost": 100,
                "optimised_monthly_cost": 75,
                "total_monthly_savings": 25,
            },
            "services": {
                "s3": {
                    "baseline_monthly_cost": 100,
                    "optimised_monthly_cost": 75,
                    "total_monthly_savings": 25,
                    "recommendations": [],
                }
            },
        }

        with tempfile.TemporaryDirectory() as tmp:
            html_path, json_path = report_generator.generate_report_files(
                payload,
                Path(tmp),
                "test report",
            )

            self.assertTrue(html_path.exists())
            self.assertTrue(json_path.exists())
            self.assertIn("Test Org", html_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["run_id"], json.loads(json_path.read_text(encoding="utf-8"))["run_id"])

    def test_report_helper_formatters_cover_edge_cases(self):
        self.assertEqual("0.00", report_generator.money("bad"))
        self.assertEqual("—", report_generator.money_or_dash(None))
        self.assertEqual("12.5", report_generator.fmt_num(12.50))
        self.assertEqual("", report_generator.format_timestamp(""))
        self.assertEqual("bad", report_generator.format_timestamp("bad"))
        self.assertIn("risk-high", report_generator.risk_badge("high"))
        self.assertIn("No top actions available", report_generator.build_top_actions({"summary": {}}))
        self.assertIn("No recommendations", report_generator.render_generic({"recommendations": []}))


if __name__ == "__main__":
    unittest.main()
