import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = PROJECT_ROOT / "flaskAPP" / "web"
if str(WEB_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_DIR))

from flask import Flask

from web_common import (
    admin_login_required,
    build_customer_bundle_data,
    customer_login_required,
    ensure_admin_superuser_support,
    find_account_by_email,
    get_enabled_service_codes,
    send_application_message_notification,
    send_application_status_notification,
    send_verification_code,
    slugify,
    verify_password,
)


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

    def test_build_customer_bundle_data_uses_all_report_emails_and_defaults(self):
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
            [
                {"report_email": "reports@example.com"},
                {"report_email": "finops@example.com"},
                {"report_email": "reports@example.com"},
            ],
        )

        self.assertEqual("org_7", payload["customer_id"])
        self.assertEqual("eu-west-2", payload["aws_region"])
        self.assertEqual("northshore-retail-group-7-finops-reports", payload["report_bucket_name"])
        self.assertEqual("reports@example.com,finops@example.com", payload["notification_email"])
        self.assertEqual("rate(30 days)", payload["schedule_expression"])
        self.assertTrue(payload["run_initial_report_on_apply"])
        self.assertTrue(payload["services"]["s3"])
        self.assertTrue(payload["services"]["rds"])
        self.assertFalse(payload["services"]["spot"])

    def test_build_customer_bundle_data_filters_invalid_recipients_and_defaults_invalid_values(self):
        data = {
            "organisation_id": "7",
            "organisation_name": "Northshore Retail Group",
            "aws_region": "not-a-region",
            "contact_email": "owner@example.com",
            "report_frequency": "yearly",
        }

        payload = build_customer_bundle_data(
            data,
            ["s3"],
            [
                {"report_email": "reports@example.com"},
                {"report_email": "bad-email"},
                {"report_email": ""},
            ],
        )

        self.assertEqual("eu-west-2", payload["aws_region"])
        self.assertEqual("rate(7 days)", payload["schedule_expression"])
        self.assertEqual("reports@example.com", payload["notification_email"])

    def test_build_customer_bundle_data_raises_for_missing_required_fields(self):
        with self.assertRaises(ValueError):
            build_customer_bundle_data(
                {
                    "organisation_id": None,
                    "organisation_name": "",
                    "contact_email": "owner@example.com",
                    "report_frequency": "weekly",
                },
                ["s3"],
                [],
            )

    def test_verify_password_returns_false_for_bad_hash(self):
        self.assertFalse(verify_password("not-a-valid-hash", "password123"))

    def test_send_verification_code_returns_false_without_smtp(self):
        app = SimpleNamespace(logger=SimpleNamespace(info=lambda *args, **kwargs: None))
        config = SimpleNamespace(
            smtp_host="",
            smtp_sender="",
            smtp_port=587,
            smtp_use_tls=True,
            smtp_username="",
            smtp_password="",
        )
        self.assertFalse(send_verification_code(app, config, "user@example.com", "Login", "123456"))

    def test_send_verification_code_sends_via_smtp_when_configured(self):
        sent_messages = []

        class FakeSMTP:
            def __init__(self, host, port, timeout):
                self.host = host
                self.port = port
                self.timeout = timeout
                self.started_tls = False
                self.logged_in = None

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def starttls(self):
                self.started_tls = True

            def login(self, username, password):
                self.logged_in = (username, password)

            def send_message(self, message):
                sent_messages.append((message["Subject"], message["To"]))

        app = SimpleNamespace(logger=SimpleNamespace(info=lambda *args, **kwargs: None))
        config = SimpleNamespace(
            smtp_host="smtp.example.com",
            smtp_sender="reports@example.com",
            smtp_port=587,
            smtp_use_tls=True,
            smtp_username="smtp-user",
            smtp_password="smtp-pass",
        )

        with patch("web_common.smtplib.SMTP", FakeSMTP):
            result = send_verification_code(app, config, "user@example.com", "Login", "123456")

        self.assertTrue(result)
        self.assertEqual([("Login verification code", "user@example.com")], sent_messages)

    def test_send_application_message_notification_sends_via_smtp_when_configured(self):
        sent_messages = []

        class FakeSMTP:
            def __init__(self, host, port, timeout):
                self.host = host
                self.port = port
                self.timeout = timeout
                self.started_tls = False
                self.logged_in = None

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def starttls(self):
                self.started_tls = True

            def login(self, username, password):
                self.logged_in = (username, password)

            def send_message(self, message):
                sent_messages.append(
                    {
                        "subject": message["Subject"],
                        "to": message["To"],
                        "body": message.get_content(),
                    }
                )

        app = SimpleNamespace(logger=SimpleNamespace(info=lambda *args, **kwargs: None))
        config = SimpleNamespace(
            smtp_host="smtp.example.com",
            smtp_sender="reports@example.com",
            smtp_port=587,
            smtp_use_tls=True,
            smtp_username="smtp-user",
            smtp_password="smtp-pass",
            app_base_url="http://127.0.0.1:5050",
        )

        with patch("web_common.smtplib.SMTP", FakeSMTP):
            result = send_application_message_notification(
                app,
                config,
                "user@example.com",
                "Sarah",
                "Northshore Retail Group",
                12,
                "admin@example.com",
            )

        self.assertTrue(result)
        self.assertEqual("user@example.com", sent_messages[0]["to"])
        self.assertIn("New message about your FinOps application", sent_messages[0]["subject"])
        self.assertIn("/customer/applications/12/messages", sent_messages[0]["body"])

    def test_send_application_status_notification_sends_via_smtp_when_configured(self):
        sent_messages = []

        class FakeSMTP:
            def __init__(self, host, port, timeout):
                self.host = host
                self.port = port
                self.timeout = timeout

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def starttls(self):
                return None

            def login(self, username, password):
                self.logged_in = (username, password)

            def send_message(self, message):
                sent_messages.append(
                    {
                        "subject": message["Subject"],
                        "to": message["To"],
                        "body": message.get_content(),
                    }
                )

        app = SimpleNamespace(logger=SimpleNamespace(info=lambda *args, **kwargs: None))
        config = SimpleNamespace(
            smtp_host="smtp.example.com",
            smtp_sender="reports@example.com",
            smtp_port=587,
            smtp_use_tls=True,
            smtp_username="smtp-user",
            smtp_password="smtp-pass",
            app_base_url="http://127.0.0.1:5050",
        )

        with patch("web_common.smtplib.SMTP", FakeSMTP):
            result = send_application_status_notification(
                app,
                config,
                "user@example.com",
                "Sarah",
                "Northshore Retail Group",
                12,
                "approved",
            )

        self.assertTrue(result)
        self.assertEqual("user@example.com", sent_messages[0]["to"])
        self.assertIn("status has been updated", sent_messages[0]["subject"])
        self.assertIn("/customer/dashboard", sent_messages[0]["body"])

    def test_ensure_admin_superuser_support_adds_column_when_missing(self):
        class FakeCursor:
            def __init__(self, fetch=None):
                self.fetch = fetch
                self.executed = []
                self.closed = False

            def execute(self, query, params=None):
                self.executed.append(" ".join(query.split()))

            def fetchone(self):
                return self.fetch

            def close(self):
                self.closed = True

        class FakeConn:
            def __init__(self):
                self.cursors = [FakeCursor(fetch=None), FakeCursor(fetch={"Field": "ignored"})]
                self.committed = False

            def cursor(self, dictionary=False):
                return self.cursors.pop(0)

            def commit(self):
                self.committed = True

        conn = FakeConn()
        ensure_admin_superuser_support(conn)
        self.assertTrue(conn.committed)

    def test_find_account_by_email_returns_customer_and_none(self):
        class FakeCursor:
            def __init__(self):
                self.calls = 0

            def execute(self, query, params=None):
                self.calls += 1

            def fetchone(self):
                if self.calls == 1:
                    return None
                return {
                    "customer_user_id": 42,
                    "organisation_id": 7,
                    "contact_name": "Sarah",
                    "email": "sarah@example.com",
                    "password_hash": "hash",
                }

        customer = find_account_by_email(FakeCursor(), "sarah@example.com")
        self.assertEqual("customer", customer["user_role"])
        self.assertEqual(7, customer["organisation_id"])

        class EmptyCursor:
            def execute(self, query, params=None):
                pass

            def fetchone(self):
                return None

        self.assertIsNone(find_account_by_email(EmptyCursor(), "missing@example.com"))

    def test_role_decorators_redirect_and_allow(self):
        app = Flask(__name__)
        app.secret_key = "test"

        @app.route("/login")
        def login_page():
            return "login"

        @app.route("/admin-only")
        @admin_login_required
        def admin_only():
            return "admin ok"

        @app.route("/customer-only")
        @customer_login_required
        def customer_only():
            return "customer ok"

        client = app.test_client()

        response = client.get("/admin-only")
        self.assertEqual(302, response.status_code)
        self.assertIn("/login", response.location)

        with client.session_transaction() as sess:
            sess["user_role"] = "admin"
        self.assertEqual(b"admin ok", client.get("/admin-only").data)

        response = client.get("/customer-only")
        self.assertEqual(302, response.status_code)
        self.assertIn("/login", response.location)

        with client.session_transaction() as sess:
            sess["user_role"] = "customer"
        self.assertEqual(b"customer ok", client.get("/customer-only").data)

        with self.assertRaises(ValueError):
            build_customer_bundle_data(
                {
                    "organisation_id": 7,
                    "organisation_name": "Acme",
                    "contact_email": "not-an-email",
                    "report_frequency": "weekly",
                },
                ["s3"],
                [],
            )


if __name__ == "__main__":
    unittest.main()
