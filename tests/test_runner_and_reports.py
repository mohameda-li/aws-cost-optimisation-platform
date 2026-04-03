import importlib
import json
import os
import sys
import tempfile
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNNER_DIR = PROJECT_ROOT / "src" / "runner"
if str(RUNNER_DIR) not in sys.path:
    sys.path.insert(0, str(RUNNER_DIR))

if "boto3" not in sys.modules:
    sys.modules["boto3"] = types.SimpleNamespace(client=lambda *args, **kwargs: object())

runner = importlib.import_module("lambda_function")
report_generator = importlib.import_module("report_generator")
s3_lambda = importlib.import_module("src.optimisers.s3.lambda_function")


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

    def test_parse_body_accepts_dict_body(self):
        payload = {"service": "s3", "total_monthly_savings": 1.25}
        result = runner._parse_body({"statusCode": 200, "body": payload})
        self.assertEqual(payload, result)

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

    def test_send_report_email_formats_polished_message(self):
        previous_env = {key: os.environ.get(key) for key in (
            "SMTP_HOST",
            "SMTP_PORT",
            "SMTP_USERNAME",
            "SMTP_PASSWORD",
            "SMTP_SENDER",
            "SMTP_USE_TLS",
            "NOTIFICATION_EMAIL",
        )}

        payload = {
            "customer": "Acme Ltd",
            "run_id": "run-123",
            "timestamp": "2026-03-29T17:00:00+00:00",
            "summary": {
                "enabled_services": ["s3", "rds"],
                "partial_run": False,
                "errors": [],
            },
            "totals": {"total_monthly_savings": 12.34},
            "report_files": {
                "s3_bucket": "reports-bucket",
                "s3_keys": {
                    "html_key": "reports/Acme/run-123.html",
                    "json_key": "reports/Acme/run-123.json",
                },
                "report_links": {
                    "html_url": "https://example.com/report.html",
                    "json_url": "https://example.com/report.json",
                },
            },
        }

        class FakeSMTP:
            instances = []

            def __init__(self, host, port, timeout):
                self.host = host
                self.port = port
                self.timeout = timeout
                self.started_tls = False
                self.logged_in = None
                self.messages = []
                FakeSMTP.instances.append(self)

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def starttls(self):
                self.started_tls = True

            def login(self, username, password):
                self.logged_in = (username, password)

            def send_message(self, message):
                self.messages.append(message)

        original_smtp = runner.smtplib.SMTP
        runner.smtplib.SMTP = FakeSMTP
        os.environ["SMTP_HOST"] = "email-smtp.example.com"
        os.environ["SMTP_PORT"] = "587"
        os.environ["SMTP_USERNAME"] = "smtp-user"
        os.environ["SMTP_PASSWORD"] = "smtp-pass"
        os.environ["SMTP_SENDER"] = "reports@example.com"
        os.environ["SMTP_USE_TLS"] = "true"
        os.environ["NOTIFICATION_EMAIL"] = "ops@example.com,finops@example.com"

        try:
            result = runner._send_report_email(payload)
        finally:
            runner.smtplib.SMTP = original_smtp
            for key, value in previous_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

        self.assertEqual("sent", result["status"])
        self.assertEqual(["ops@example.com", "finops@example.com"], result["recipients"])
        self.assertEqual(1, len(FakeSMTP.instances))
        smtp = FakeSMTP.instances[0]
        self.assertTrue(smtp.started_tls)
        self.assertEqual(("smtp-user", "smtp-pass"), smtp.logged_in)
        self.assertEqual(1, len(smtp.messages))
        message = smtp.messages[0]
        self.assertEqual("Your scheduled FinOps report is ready - Acme Ltd", message["Subject"])
        self.assertEqual("reports@example.com", message["From"])
        self.assertEqual("ops@example.com, finops@example.com", message["To"])
        body = message.get_body(preferencelist=("plain",)).get_content()
        self.assertIn("Your scheduled FinOps Automation report for Acme Ltd is now ready.", body)
        self.assertIn("Use the links below to open your latest report.", body)
        self.assertIn("View report\nhttps://example.com/report.html", body)
        self.assertIn("Download data (JSON)\nhttps://example.com/report.json", body)
        self.assertIn("Estimated monthly savings: GBP 12.34", body)
        self.assertIn("Thank you,\nFinOps Automation", body)
        html_body = message.get_body(preferencelist=("html",)).get_content()
        self.assertIn(">View report<", html_body)
        self.assertIn(">Download data<", html_body)
        self.assertIn("https://example.com/report.html", html_body)
        self.assertNotIn("S3 bucket:", body)

    def test_send_report_email_skips_when_smtp_not_configured(self):
        previous_host = os.environ.get("SMTP_HOST")
        previous_sender = os.environ.get("SMTP_SENDER")
        previous_recipients = os.environ.get("NOTIFICATION_EMAIL")
        os.environ.pop("SMTP_HOST", None)
        os.environ.pop("SMTP_SENDER", None)
        os.environ["NOTIFICATION_EMAIL"] = "ops@example.com"

        try:
            result = runner._send_report_email({"customer": "Acme Ltd"})
        finally:
            if previous_host is None:
                os.environ.pop("SMTP_HOST", None)
            else:
                os.environ["SMTP_HOST"] = previous_host
            if previous_sender is None:
                os.environ.pop("SMTP_SENDER", None)
            else:
                os.environ["SMTP_SENDER"] = previous_sender
            if previous_recipients is None:
                os.environ.pop("NOTIFICATION_EMAIL", None)
            else:
                os.environ["NOTIFICATION_EMAIL"] = previous_recipients

        self.assertEqual("skipped", result["status"])

    def test_send_report_email_returns_error_for_invalid_smtp_port(self):
        previous_env = {key: os.environ.get(key) for key in (
            "SMTP_HOST",
            "SMTP_PORT",
            "SMTP_SENDER",
            "NOTIFICATION_EMAIL",
        )}
        os.environ["SMTP_HOST"] = "email-smtp.example.com"
        os.environ["SMTP_PORT"] = "bad-port"
        os.environ["SMTP_SENDER"] = "reports@example.com"
        os.environ["NOTIFICATION_EMAIL"] = "ops@example.com"

        try:
            result = runner._send_report_email({"customer": "Acme Ltd"})
        finally:
            for key, value in previous_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

        self.assertEqual("error", result["status"])
        self.assertEqual("Invalid SMTP port configuration", result["reason"])

    def test_build_report_links_creates_presigned_urls_for_uploaded_objects(self):
        class FakeS3Client:
            def __init__(self):
                self.calls = []

            def generate_presigned_url(self, operation, Params, ExpiresIn):
                self.calls.append((operation, Params, ExpiresIn))
                return f"https://example.com/{Params['Key']}"

        client = FakeS3Client()
        original_client = runner.boto3.client
        runner.boto3.client = lambda **kwargs: client
        try:
            links = runner._build_report_links(
                client,
                "reports-bucket",
                {
                    "html_key": "reports/Acme/run-123.html",
                    "json_key": "reports/Acme/run-123.json",
                },
                region="eu-west-2",
            )
        finally:
            runner.boto3.client = original_client

        self.assertEqual("https://example.com/reports/Acme/run-123.html", links["html_url"])
        self.assertEqual("https://example.com/reports/Acme/run-123.json", links["json_url"])
        self.assertEqual(2, len(client.calls))

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

    def test_prune_old_reports_keeps_latest_twenty_runs(self):
        class FakePaginator:
            def paginate(self, **kwargs):
                base = datetime(2026, 3, 1, tzinfo=timezone.utc)
                contents = []
                for idx in range(25):
                    run_id = f"run-{idx:02d}"
                    stamp = base.replace(day=min(idx + 1, 28))
                    contents.extend(
                        [
                            {"Key": f"reports/acme/{run_id}.html", "LastModified": stamp},
                            {"Key": f"reports/acme/{run_id}.json", "LastModified": stamp},
                        ]
                    )
                return [{"Contents": contents}]

        class FakeS3Client:
            def __init__(self):
                self.deleted_batches = []

            def get_paginator(self, name):
                self.paginator_name = name
                return FakePaginator()

            def delete_objects(self, Bucket, Delete):
                self.deleted_batches.append((Bucket, Delete["Objects"]))
                return {"Deleted": Delete["Objects"]}

        client = FakeS3Client()
        result = runner._prune_old_reports(client, "reports-bucket", "acme", keep_latest=20)

        self.assertEqual("list_objects_v2", client.paginator_name)
        self.assertEqual(20, result["kept_runs"])
        self.assertEqual(5, result["deleted_runs"])
        self.assertEqual(10, result["deleted_objects"])
        deleted_keys = [item["Key"] for _, batch in client.deleted_batches for item in batch]
        self.assertIn("reports/acme/run-00.html", deleted_keys)
        self.assertIn("reports/acme/run-04.json", deleted_keys)
        self.assertNotIn("reports/acme/run-24.html", deleted_keys)


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

    def test_build_html_uses_shared_report_classes_for_summary(self):
        payload = {
            "customer": "Test Org",
            "run_id": "run-456",
            "timestamp": "2026-03-13T10:00:00+00:00",
            "summary": {"savings_percent": 12.5, "top_actions": []},
            "totals": {
                "baseline_monthly_cost": 50,
                "optimised_monthly_cost": 40,
                "total_monthly_savings": 10,
            },
            "services": {
                "ecs": {
                    "recommendations": [],
                    "details": {"reason": "No ECS services found to analyse.", "region": "eu-west-2"},
                }
            },
        }

        html = report_generator.build_html(payload)
        self.assertIn("section--compact", html)
        self.assertIn("kpi-note", html)
        self.assertIn("No ECS services found to analyse.", html)
        self.assertNotIn("style=\"margin-top:10px;\"", html)
        self.assertNotIn("style=\"font-size:14px;\"", html)

    def test_render_generic_empty_state_includes_reason_and_details(self):
        html = report_generator.render_generic(
            {
                "recommendations": [],
                "details": {
                    "reason": "Nothing to analyse.",
                    "region": "eu-west-2",
                    "lookback_days": 7,
                },
            }
        )
        self.assertIn("empty-state", html)
        self.assertIn("Nothing to analyse.", html)
        self.assertIn("Region:", html)
        self.assertIn("Lookback days:", html)
        self.assertNotIn("<table>", html)

    def test_report_helper_formatters_cover_edge_cases(self):
        self.assertEqual("0.00", report_generator.money("bad"))
        self.assertEqual("—", report_generator.money_or_dash(None))
        self.assertEqual("12.5", report_generator.fmt_num(12.50))
        self.assertEqual("", report_generator.format_timestamp(""))
        self.assertEqual("bad", report_generator.format_timestamp("bad"))
        self.assertIn("risk-high", report_generator.risk_badge("high"))
        self.assertIn("No top actions available", report_generator.build_top_actions({"summary": {}}))

    def test_generate_report_files_handles_malformed_payload_shapes(self):
        with tempfile.TemporaryDirectory() as tmp:
            html_path, json_path = report_generator.generate_report_files(
                {"services": ["unexpected"], "totals": "unexpected", "summary": None},
                Path(tmp),
                "bad payload",
            )

            html = html_path.read_text(encoding="utf-8")
            saved = json.loads(json_path.read_text(encoding="utf-8"))

        self.assertIn("FinOps Automation Report", html)
        self.assertIn("Top actions", html)
        self.assertEqual(["unexpected"], saved["services"])

    def test_report_helper_renderers_cover_additional_branches(self):
        self.assertEqual("run", report_generator.sanitize_filename(""))
        self.assertIn("risk-low", report_generator.risk_badge("low"))
        self.assertIn("risk-medium", report_generator.risk_badge("medium"))
        self.assertIn("risk-unknown", report_generator.risk_badge(None))
        self.assertIn("No recommendations", report_generator.table(["A"], []))
        self.assertIn("01 Jan 2026", report_generator.format_timestamp("2026-01-01T10:00:00+00:00"))

    def test_build_top_actions_and_render_generic_with_recommendations(self):
        top_html = report_generator.build_top_actions(
            {
                "summary": {
                    "top_actions": [
                        {
                            "service": "s3",
                            "resource_id": "bucket-a",
                            "action": "move_to_ia",
                            "risk_level": "low",
                            "estimated_monthly_savings": 2.5,
                        }
                    ]
                }
            }
        )
        self.assertIn("bucket-a", top_html)
        self.assertIn("move_to_ia", top_html)

        generic_html = report_generator.render_generic(
            {
                "recommendations": [
                    {
                        "bucket": "bucket-a",
                        "recommended_storage_class": "STANDARD_IA",
                        "baseline_monthly_cost": 4.0,
                        "optimised_monthly_cost": 1.5,
                        "estimated_monthly_savings": 2.5,
                        "risk_level": "low",
                        "rationale": "Infrequently accessed objects can move to a cheaper storage tier.",
                    }
                ]
            }
        )
        self.assertIn("STANDARD_IA", generic_html)
        self.assertIn("bucket-a", generic_html)
        self.assertIn("risk-low", generic_html)


class TestS3LambdaBehaviour(unittest.TestCase):
    def test_report_bucket_is_excluded_from_scan(self):
        previous_bucket = os.environ.get("REPORT_BUCKET_NAME")
        os.environ["REPORT_BUCKET_NAME"] = "reports-bucket"

        class FakeS3Client:
            def list_buckets(self):
                return {"Buckets": [{"Name": "reports-bucket"}, {"Name": "customer-data"}]}

            def list_objects_v2(self, **kwargs):
                return {
                    "Contents": [{"Size": 1024, "StorageClass": "STANDARD"}],
                    "IsTruncated": False,
                }

        def fake_cost(*args, **kwargs):
            return [{"bucket": "customer-data"}]

        try:
            original_client = s3_lambda.boto3.client
            original_cost = s3_lambda.calculate_s3_cost
            original_recs = s3_lambda.recommend_s3_optimisations
            original_savings = s3_lambda.estimate_s3_savings
            s3_lambda.boto3.client = lambda *args, **kwargs: FakeS3Client()
            s3_lambda.calculate_s3_cost = fake_cost
            s3_lambda.recommend_s3_optimisations = lambda rows: []
            s3_lambda.estimate_s3_savings = lambda recs, pricing_path: {
                "current_cost": 0.0,
                "projected_cost": 0.0,
                "estimated_savings": 0.0,
            }

            response = s3_lambda.lambda_handler({}, None)
            body = json.loads(response["body"])
            self.assertEqual(1, body["details"]["buckets_scanned"])
            self.assertEqual(["reports-bucket"], body["details"]["excluded_buckets"])
        finally:
            s3_lambda.boto3.client = original_client
            s3_lambda.calculate_s3_cost = original_cost
            s3_lambda.recommend_s3_optimisations = original_recs
            s3_lambda.estimate_s3_savings = original_savings
            if previous_bucket is None:
                os.environ.pop("REPORT_BUCKET_NAME", None)
            else:
                os.environ["REPORT_BUCKET_NAME"] = previous_bucket


if __name__ == "__main__":
    unittest.main()
