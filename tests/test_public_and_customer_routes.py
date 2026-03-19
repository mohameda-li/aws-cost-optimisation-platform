import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = PROJECT_ROOT / "flaskAPP" / "web"
if str(WEB_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_DIR))

import app as web_app


class RecordingConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False
        self.rolled_back = False

    def cursor(self, dictionary=True):
        return self._cursor

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        pass


class PublicApplyCursor:
    def __init__(self, org=None, existing_user=None):
        self.org = org
        self.existing_user = existing_user
        self.fetchone_calls = 0
        self.lastrowid = None
        self.next_insert_id = 7
        self.executed = []

    def execute(self, query, params=None):
        self.executed.append((" ".join(query.split()), params))
        if query.strip().startswith("INSERT"):
            self.lastrowid = self.next_insert_id
            self.next_insert_id += 1

    def fetchone(self):
        self.fetchone_calls += 1
        if self.fetchone_calls == 1 and self.org is None and self.existing_user is not None:
            return self.existing_user
        if self.fetchone_calls == 1:
            return self.org
        if self.fetchone_calls == 2:
            return self.existing_user
        return None

    def close(self):
        pass


class CustomerDownloadCursor:
    def __init__(self, application_row, service_rows=None, report_row=None):
        self.application_row = application_row
        self.service_rows = service_rows or []
        self.report_row = report_row
        self.fetchone_calls = 0

    def execute(self, query, params=None):
        self.last_query = " ".join(query.split())

    def fetchone(self):
        self.fetchone_calls += 1
        if self.fetchone_calls == 1:
            return self.application_row
        if self.fetchone_calls == 2:
            return self.report_row
        return None

    def fetchall(self):
        return list(self.service_rows)

    def close(self):
        pass


class CustomerDashboardCursor:
    def __init__(self, applications, service_rows, recipient_rows, count_rows=None):
        self.fetchall_values = iter([applications, service_rows, recipient_rows])
        self.count_rows = iter(count_rows or [{"count": 0}])
        self.last_query = ""

    def execute(self, query, params=None):
        self.last_query = " ".join(query.split())

    def fetchone(self):
        if "COUNT(*) AS count FROM application_messages" in self.last_query:
            return next(self.count_rows)
        if "SELECT sender_role FROM application_messages" in self.last_query:
            return {"sender_role": "admin"}
        return None

    def fetchall(self):
        return next(self.fetchall_values)

    def close(self):
        pass


class CustomerEditCursor:
    def __init__(self, app_row, service_rows=None, report_row=None):
        self.app_row = app_row
        self.service_rows = service_rows or []
        self.report_row = report_row
        self.fetchone_calls = 0
        self.executed = []

    def execute(self, query, params=None):
        self.executed.append((" ".join(query.split()), params))

    def fetchone(self):
        self.fetchone_calls += 1
        if self.fetchone_calls == 1:
            return self.app_row
        if self.fetchone_calls == 2:
            return self.report_row
        return None

    def fetchall(self):
        return list(self.service_rows)

    def close(self):
        pass


class CustomerUpdateCursor:
    def __init__(self, app_row):
        self.app_row = app_row
        self.fetchone_calls = 0
        self.executed = []

    def execute(self, query, params=None):
        self.executed.append((" ".join(query.split()), params))

    def fetchone(self):
        self.fetchone_calls += 1
        if self.fetchone_calls == 1:
            return self.app_row
        return None

    def close(self):
        pass


class CustomerMessageCursor:
    def __init__(self, app_row, messages=None):
        self.app_row = app_row
        self.messages = messages or []
        self.last_query = ""
        self.executed = []

    def execute(self, query, params=None):
        self.last_query = " ".join(query.split())
        self.executed.append((self.last_query, params))

    def fetchone(self):
        if "FROM applications" in self.last_query:
            return self.app_row
        return None

    def fetchall(self):
        if "FROM application_messages" in self.last_query:
            return list(self.messages)
        return []

    def close(self):
        pass


class TestPublicAndCustomerRoutes(unittest.TestCase):
    def setUp(self):
        web_app.app.config["TESTING"] = True
        self.client = web_app.app.test_client()

    def test_apply_submit_rejects_invalid_form(self):
        response = self.client.post(
            "/apply",
            data={
                "organisation_name": "",
                "contact_name": "",
                "contact_email": "bad",
                "password": "short",
                "confirm_password": "mismatch",
                "report_email": "bad",
                "services": [],
            },
        )
        self.assertEqual(400, response.status_code)
        self.assertIn(b"Company name is required.", response.data)
        self.assertIn(b"Select at least one service to enable.", response.data)

    def test_apply_submit_rejects_existing_customer_email(self):
        cursor = PublicApplyCursor(org=None, existing_user={"customer_user_id": 99})
        conn = RecordingConnection(cursor)

        with patch("app.get_db_connection", return_value=conn):
            response = self.client.post(
                "/apply",
                data={
                    "organisation_name": "Northshore Retail Group",
                    "contact_name": "Sarah Ahmed",
                    "contact_email": "sarah@example.com",
                    "password": "password123",
                    "confirm_password": "password123",
                    "report_email": "reports@example.com",
                    "aws_region": "eu-west-2",
                    "report_frequency": "weekly",
                    "services": ["s3", "rds"],
                },
            )

        self.assertEqual(400, response.status_code)
        self.assertFalse(conn.rolled_back)
        self.assertFalse(conn.committed)
        self.assertIn(b"An account with that email already exists.", response.data)

    def test_apply_submit_success_sets_customer_session(self):
        lookup_cursor = PublicApplyCursor(org=None, existing_user=None)
        lookup_conn = RecordingConnection(lookup_cursor)

        with patch("app.get_db_connection", return_value=lookup_conn), patch("app.send_verification_code"):
            response = self.client.post(
                "/apply",
                data={
                    "organisation_name": "Northshore Retail Group",
                    "contact_name": "Sarah Ahmed",
                    "contact_email": "sarah@example.com",
                    "password": "password123",
                    "confirm_password": "password123",
                    "report_email": "reports@example.com",
                    "aws_region": "eu-west-2",
                    "report_frequency": "weekly",
                    "notes": "Please review quickly",
                    "services": ["s3", "rds"],
                },
            )

        self.assertEqual(302, response.status_code)
        self.assertIn("/apply/verify", response.location)
        with self.client.session_transaction() as sess:
            self.assertEqual("sarah@example.com", sess["pending_application_verification"]["email"])
            self.assertTrue(sess["pending_application_verification"]["code"])

    def test_apply_verify_code_completes_application(self):
        lookup_cursor = PublicApplyCursor(org=None, existing_user=None)
        lookup_conn = RecordingConnection(lookup_cursor)
        create_cursor = PublicApplyCursor(org=None, existing_user=None)
        create_conn = RecordingConnection(create_cursor)

        with patch("app.get_db_connection", return_value=lookup_conn), patch("app.send_verification_code"):
            self.client.post(
                "/apply",
                data={
                    "organisation_name": "Northshore Retail Group",
                    "contact_name": "Sarah Ahmed",
                    "contact_email": "sarah@example.com",
                    "password": "password123",
                    "confirm_password": "password123",
                    "report_email": "reports@example.com",
                    "aws_region": "eu-west-2",
                    "report_frequency": "weekly",
                    "notes": "Please review quickly",
                    "services": ["s3", "rds"],
                },
            )

        with self.client.session_transaction() as sess:
            code = sess["pending_application_verification"]["code"]

        with patch("app.get_db_connection", return_value=create_conn), patch("app.hash_password", return_value="hashed-password"):
            response = self.client.post("/apply/verify", data={"action": "verify", "verification_code": code})

        self.assertEqual(302, response.status_code)
        self.assertIn("/customer/dashboard?banner=submitted", response.location)
        self.assertTrue(create_conn.committed)
        with self.client.session_transaction() as sess:
            self.assertEqual("customer", sess["user_role"])
            self.assertEqual("sarah@example.com", sess["customer_email"])
            self.assertEqual(7, sess["organisation_id"])


    def test_customer_download_bundle_rejects_pending_application(self):
        cursor = CustomerDownloadCursor(
            {
                "application_id": 1,
                "status": "pending",
                "organisation_id": 7,
                "contact_name": "Sarah Ahmed",
                "contact_email": "sarah@example.com",
                "organisation_name": "Northshore Retail Group",
                "onboarding_id": 10,
                "aws_region": "eu-west-2",
                "report_frequency": "weekly",
            }
        )
        conn = RecordingConnection(cursor)

        with self.client.session_transaction() as sess:
            sess["user_role"] = "customer"
            sess["customer_user_id"] = 42

        with patch("app.get_db_connection", return_value=conn):
            response = self.client.get("/customer/download-bundle/1")

        self.assertEqual(403, response.status_code)
        self.assertIn(b"under review", response.data)

    def test_customer_download_bundle_serves_generated_zip(self):
        cursor = CustomerDownloadCursor(
            {
                "application_id": 1,
                "status": "approved",
                "organisation_id": 7,
                "contact_name": "Sarah Ahmed",
                "contact_email": "sarah@example.com",
                "organisation_name": "Northshore Retail Group",
                "onboarding_id": 10,
                "aws_region": "eu-west-2",
                "report_frequency": "weekly",
            },
            service_rows=[{"service_code": "s3"}, {"service_code": "rds"}],
            report_row={"report_email": "reports@example.com"},
        )
        conn = RecordingConnection(cursor)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            bundle_dir = tmp_root / "generated_bundles"
            bundle_dir.mkdir(parents=True, exist_ok=True)
            zip_name = "org_7-deployment.zip"
            (bundle_dir / zip_name).write_bytes(b"zip-data")

            with self.client.session_transaction() as sess:
                sess["user_role"] = "customer"
                sess["customer_user_id"] = 42

            with patch("app.get_db_connection", return_value=conn), patch.object(
                web_app.app, "root_path", str(tmp_root)
            ), patch("app.build_customer_bundle_data", return_value={"customer_id": "org_7"}), patch(
                "app.create_customer_bundle", return_value={"zip_filename": zip_name}
            ):
                response = self.client.get("/customer/download-bundle/1")

        self.assertEqual(200, response.status_code)
        self.assertEqual("application/zip", response.mimetype)
        self.assertIn('attachment; filename=org_7-deployment.zip', response.headers["Content-Disposition"])
        response.close()

    def test_customer_dashboard_renders_services_and_report_recipients(self):
        cursor = CustomerDashboardCursor(
            applications=[
                {
                    "application_id": 1,
                    "status": "pending",
                    "notes": "Approved",
                    "created_at": "2026-03-13",
                    "contact_name": "Sarah Ahmed",
                    "contact_email": "sarah@example.com",
                    "organisation_name": "Northshore Retail Group",
                    "onboarding_id": 10,
                    "aws_region": "eu-west-2",
                    "report_frequency": "weekly",
                }
            ],
            service_rows=[{"service_name": "Amazon S3", "service_code": "s3"}],
            recipient_rows=[{"report_email": "reports@example.com"}],
            count_rows=[{"count": 2}],
        )
        conn = RecordingConnection(cursor)

        with self.client.session_transaction() as sess:
            sess["user_role"] = "customer"
            sess["customer_user_id"] = 42

        with patch("app.get_db_connection", return_value=conn):
            response = self.client.get("/customer/dashboard")

        self.assertEqual(200, response.status_code)
        self.assertIn(b"Amazon S3", response.data)
        self.assertIn(b"reports@example.com", response.data)
        self.assertIn(b"Edit application", response.data)
        self.assertIn(b"Withdraw application", response.data)
        self.assertIn(b"Open conversation (2)", response.data)

    def test_customer_dashboard_renders_edit_for_approved_application(self):
        cursor = CustomerDashboardCursor(
            applications=[
                {
                    "application_id": 1,
                    "status": "approved",
                    "notes": "Approved",
                    "created_at": "2026-03-13",
                    "contact_name": "Sarah Ahmed",
                    "contact_email": "sarah@example.com",
                    "organisation_name": "Northshore Retail Group",
                    "onboarding_id": 10,
                    "aws_region": "eu-west-2",
                    "report_frequency": "weekly",
                }
            ],
            service_rows=[{"service_name": "Amazon S3", "service_code": "s3"}],
            recipient_rows=[{"report_email": "reports@example.com"}],
            count_rows=[{"count": 1}],
        )
        conn = RecordingConnection(cursor)

        with self.client.session_transaction() as sess:
            sess["user_role"] = "customer"
            sess["customer_user_id"] = 42

        with patch("app.get_db_connection", return_value=conn):
            response = self.client.get("/customer/dashboard")

        self.assertEqual(200, response.status_code)
        self.assertIn(b"Download Deployment Bundle", response.data)
        self.assertIn(b"Edit application", response.data)
        self.assertIn(b"return to pending", response.data)
        self.assertIn(b"Open conversation (1)", response.data)

    def test_customer_application_messages_renders_thread(self):
        cursor = CustomerMessageCursor(
            {
                "application_id": 1,
                "status": "pending",
                "organisation_name": "Northshore Retail Group",
                "contact_name": "Sarah Ahmed",
                "contact_email": "sarah@example.com",
            },
            messages=[
                {
                    "sender_role": "customer",
                    "sender_name": "Sarah Ahmed",
                    "message_body": "Can we change the region?",
                    "created_at": "2026-03-18 16:00",
                }
            ],
        )
        conn = RecordingConnection(cursor)

        with self.client.session_transaction() as sess:
            sess["user_role"] = "customer"
            sess["customer_user_id"] = 42

        with patch("app.get_db_connection", return_value=conn):
            response = self.client.get("/customer/applications/1/messages")

        self.assertEqual(200, response.status_code)
        self.assertIn(b"Contact an Admin", response.data)
        self.assertIn(b"Can we change the region?", response.data)

    def test_customer_application_messages_posts_message(self):
        cursor = CustomerMessageCursor({"application_id": 1})
        conn = RecordingConnection(cursor)

        with self.client.session_transaction() as sess:
            sess["user_role"] = "customer"
            sess["customer_user_id"] = 42
            sess["customer_name"] = "Sarah Ahmed"

        with patch("app.get_db_connection", return_value=conn):
            response = self.client.post("/customer/applications/1/messages", data={"message_body": "Please review this."})

        self.assertEqual(302, response.status_code)
        self.assertIn("/customer/applications/1/messages", response.location)
        self.assertTrue(conn.committed)
        self.assertTrue(any("INSERT INTO application_messages" in query for query, _ in cursor.executed))

    def test_edit_application_renders_pending_form(self):
        cursor = CustomerEditCursor(
            app_row={
                "application_id": 1,
                "status": "pending",
                "notes": "Please review",
                "contact_name": "Sarah Ahmed",
                "contact_email": "sarah@example.com",
                "organisation_id": 7,
                "organisation_name": "Northshore Retail Group",
                "onboarding_id": 10,
                "aws_region": "eu-west-2",
                "report_frequency": "weekly",
            },
            service_rows=[{"service_code": "s3"}, {"service_code": "rds"}],
            report_row={"report_email": "reports@example.com"},
        )
        conn = RecordingConnection(cursor)

        with self.client.session_transaction() as sess:
            sess["user_role"] = "customer"
            sess["customer_user_id"] = 42

        with patch("app.get_db_connection", return_value=conn):
            response = self.client.get("/customer/applications/1/edit")

        self.assertEqual(200, response.status_code)
        self.assertIn(b"Edit application", response.data)
        self.assertIn(b"Northshore Retail Group", response.data)
        self.assertIn(b"reports@example.com", response.data)

    def test_update_application_saves_pending_changes(self):
        cursor = CustomerUpdateCursor(
            {
                "application_id": 1,
                "status": "pending",
                "organisation_id": 7,
                "contact_email": "sarah@example.com",
                "onboarding_id": 10,
            }
        )
        conn = RecordingConnection(cursor)

        with self.client.session_transaction() as sess:
            sess["user_role"] = "customer"
            sess["customer_user_id"] = 42

        with patch("app.get_db_connection", return_value=conn):
            response = self.client.post(
                "/customer/applications/1/edit",
                data={
                    "organisation_name": "Updated Retail Group",
                    "contact_name": "Sarah Ahmed",
                    "report_email": "finops@example.com",
                    "aws_region": "eu-west-1",
                    "report_frequency": "monthly",
                    "notes": "Updated details",
                    "services": ["s3", "spot"],
                },
            )

        self.assertEqual(302, response.status_code)
        self.assertIn("/customer/dashboard?banner=updated", response.location)
        self.assertTrue(conn.committed)
        self.assertTrue(any("UPDATE organisations SET organisation_name" in query for query, _ in cursor.executed))
        self.assertTrue(any("DELETE FROM onboarding_services" in query for query, _ in cursor.executed))
        self.assertTrue(any("INSERT INTO onboarding_services" in query for query, _ in cursor.executed))

    def test_update_application_moves_approved_back_to_pending(self):
        cursor = CustomerUpdateCursor(
            {
                "application_id": 1,
                "status": "approved",
                "organisation_id": 7,
                "contact_email": "sarah@example.com",
                "onboarding_id": 10,
            }
        )
        conn = RecordingConnection(cursor)

        with self.client.session_transaction() as sess:
            sess["user_role"] = "customer"
            sess["customer_user_id"] = 42

        with patch("app.get_db_connection", return_value=conn):
            response = self.client.post(
                "/customer/applications/1/edit",
                data={
                    "organisation_name": "Updated Retail Group",
                    "contact_name": "Sarah Ahmed",
                    "report_email": "finops@example.com",
                    "aws_region": "eu-west-1",
                    "report_frequency": "monthly",
                    "notes": "Updated details",
                    "services": ["s3", "spot"],
                },
            )

        self.assertEqual(302, response.status_code)
        self.assertIn("/customer/dashboard?banner=resubmitted", response.location)
        self.assertTrue(conn.committed)
        self.assertTrue(any("UPDATE applications SET status = 'pending'" in query for query, _ in cursor.executed))

    def test_withdraw_application_removes_pending_record(self):
        cursor = CustomerUpdateCursor(
            {
                "application_id": 1,
                "status": "pending",
            }
        )
        conn = RecordingConnection(cursor)

        with self.client.session_transaction() as sess:
            sess["user_role"] = "customer"
            sess["customer_user_id"] = 42

        with patch("app.get_db_connection", return_value=conn):
            response = self.client.post("/customer/applications/1/withdraw")

        self.assertEqual(302, response.status_code)
        self.assertIn("/customer/dashboard?banner=withdrawn", response.location)
        self.assertTrue(conn.committed)
        self.assertTrue(any("DELETE FROM applications WHERE application_id" in query for query, _ in cursor.executed))

    def test_customer_download_bundle_returns_404_when_application_missing(self):
        cursor = CustomerDownloadCursor(None)
        conn = RecordingConnection(cursor)

        with self.client.session_transaction() as sess:
            sess["user_role"] = "customer"
            sess["customer_user_id"] = 42

        with patch("app.get_db_connection", return_value=conn):
            response = self.client.get("/customer/download-bundle/999")

        self.assertEqual(404, response.status_code)
        self.assertIn(b"Application not found", response.data)

    def test_customer_download_bundle_rejects_rejected_application(self):
        cursor = CustomerDownloadCursor(
            {
                "application_id": 1,
                "status": "rejected",
                "organisation_id": 7,
                "contact_name": "Sarah Ahmed",
                "contact_email": "sarah@example.com",
                "organisation_name": "Northshore Retail Group",
                "onboarding_id": 10,
                "aws_region": "eu-west-2",
                "report_frequency": "weekly",
            }
        )
        conn = RecordingConnection(cursor)

        with self.client.session_transaction() as sess:
            sess["user_role"] = "customer"
            sess["customer_user_id"] = 42

        with patch("app.get_db_connection", return_value=conn):
            response = self.client.get("/customer/download-bundle/1")

        self.assertEqual(403, response.status_code)
        self.assertIn(b"not approved", response.data)

    def test_customer_download_bundle_handles_generation_failure(self):
        cursor = CustomerDownloadCursor(
            {
                "application_id": 1,
                "status": "approved",
                "organisation_id": 7,
                "contact_name": "Sarah Ahmed",
                "contact_email": "sarah@example.com",
                "organisation_name": "Northshore Retail Group",
                "onboarding_id": 10,
                "aws_region": "eu-west-2",
                "report_frequency": "weekly",
            },
            service_rows=[{"service_code": "s3"}],
            report_row={"report_email": "reports@example.com"},
        )
        conn = RecordingConnection(cursor)

        with self.client.session_transaction() as sess:
            sess["user_role"] = "customer"
            sess["customer_user_id"] = 42

        with patch("app.get_db_connection", return_value=conn), patch(
            "app.build_customer_bundle_data", return_value={"customer_id": "org_7"}
        ), patch("app.create_customer_bundle", side_effect=RuntimeError("boom")):
            response = self.client.get("/customer/download-bundle/1")

        self.assertEqual(500, response.status_code)
        self.assertIn(b"Bundle generation failed", response.data)

    def test_customer_download_bundle_handles_missing_generated_zip(self):
        cursor = CustomerDownloadCursor(
            {
                "application_id": 1,
                "status": "approved",
                "organisation_id": 7,
                "contact_name": "Sarah Ahmed",
                "contact_email": "sarah@example.com",
                "organisation_name": "Northshore Retail Group",
                "onboarding_id": 10,
                "aws_region": "eu-west-2",
                "report_frequency": "weekly",
            },
            service_rows=[{"service_code": "s3"}],
            report_row={"report_email": "reports@example.com"},
        )
        conn = RecordingConnection(cursor)

        with tempfile.TemporaryDirectory() as tmp:
            with self.client.session_transaction() as sess:
                sess["user_role"] = "customer"
                sess["customer_user_id"] = 42

            with patch("app.get_db_connection", return_value=conn), patch.object(
                web_app.app, "root_path", tmp
            ), patch("app.build_customer_bundle_data", return_value={"customer_id": "org_7"}), patch(
                "app.create_customer_bundle", return_value={"zip_filename": "missing.zip"}
            ):
                response = self.client.get("/customer/download-bundle/1")

        self.assertEqual(404, response.status_code)
        self.assertIn(b"Bundle file missing", response.data)


if __name__ == "__main__":
    unittest.main()
