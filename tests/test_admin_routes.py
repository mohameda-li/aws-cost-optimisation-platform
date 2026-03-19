import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = PROJECT_ROOT / "flaskAPP" / "web"
if str(WEB_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_DIR))

import app as web_app


class AdminBaseCursor:
    def __init__(self):
        self.executed = []
        self.last_query = ""

    def execute(self, query, params=None):
        self.last_query = " ".join(query.split())
        self.executed.append((self.last_query, params))

    def fetchone(self):
        if "SHOW COLUMNS FROM admins LIKE 'is_superuser'" in self.last_query:
            return {"Field": "is_superuser"}
        return None

    def close(self):
        pass


class AdminApprovalCursor(AdminBaseCursor):
    def __init__(self):
        super().__init__()
        self.fetchone_calls = 0

    def fetchone(self):
        self.fetchone_calls += 1
        if self.fetchone_calls == 1:
            return {
                "application_id": 12,
                "organisation_id": 7,
                "contact_name": "Sarah Ahmed",
                "contact_email": "sarah@example.com",
                "organisation_name": "Northshore Retail Group",
                "onboarding_id": 10,
                "aws_region": "eu-west-2",
                "report_frequency": "weekly",
            }
        if self.fetchone_calls == 2:
            return {"report_email": "reports@example.com"}
        return None

    def fetchall(self):
        return [{"service_code": "s3"}, {"service_code": "rds"}]


class AdminDeleteCursor(AdminBaseCursor):
    def fetchone(self):
        return {"count": 1}


class AdminDashboardCursor(AdminBaseCursor):
    def __init__(self):
        super().__init__()
        self.fetchone_values = iter([{"count": 2}, {"count": 5}, {"count": 4}])

    def fetchone(self):
        return next(self.fetchone_values)

    def fetchall(self):
        return [
            {
                "application_id": 1,
                "organisation_name": "Northshore",
                "contact_name": "Sarah",
                "contact_email": "sarah@example.com",
                "status": "pending",
                "created_at": "2026-03-13",
            }
        ]


class AdminApplicationsCursor(AdminBaseCursor):
    def __init__(self):
        super().__init__()
        self.last_query = ""
        self.fetchall_values = iter(
            [
                [{"application_id": 1, "onboarding_id": 10, "organisation_name": "Northshore"}],
                [{"service_name": "Amazon S3", "service_code": "s3"}],
                [{"report_email": "reports@example.com"}],
            ]
        )

    def execute(self, query, params=None):
        self.last_query = " ".join(query.split())
        self.executed.append((self.last_query, params))

    def fetchone(self):
        if "COUNT(*) AS count FROM application_messages" in self.last_query:
            return {"count": 2}
        if "SELECT sender_role FROM application_messages" in self.last_query:
            return {"sender_role": "customer"}
        return None

    def fetchall(self):
        return next(self.fetchall_values)


class AdminApplicationDetailCursor(AdminBaseCursor):
    def __init__(self, approved=True):
        super().__init__()
        self.last_params = None
        self.approved = approved

    def execute(self, query, params=None):
        self.last_query = " ".join(query.split())
        self.last_params = params
        self.executed.append((self.last_query, params))

    def fetchone(self):
        if "FROM applications a" in self.last_query:
            return {
                "application_id": 1,
                "status": "approved" if self.approved else "pending",
                "notes": "Needs review",
                "created_at": "2026-03-18 16:00",
                "customer_user_id": 9,
                "contact_name": "Sarah",
                "contact_email": "sarah@example.com",
                "organisation_id": 7,
                "organisation_name": "Northshore",
                "onboarding_id": 10,
                "aws_region": "eu-west-2",
                "report_frequency": "weekly",
                "onboarding_updated_at": "2026-03-18 17:00",
            }
        if "COUNT(*) AS count FROM application_messages" in self.last_query:
            return {"count": 2}
        if "SELECT report_email FROM onboarding_report_recipients" in self.last_query:
            return {"report_email": "reports@example.com"}
        return None

    def fetchall(self):
        if "FROM onboarding_services" in self.last_query:
            return [{"service_name": "Amazon S3", "service_code": "s3"}]
        if "FROM onboarding_report_recipients" in self.last_query:
            return [{"report_email": "reports@example.com"}]
        if "FROM application_messages" in self.last_query:
            return [
                {
                    "sender_role": "customer",
                    "sender_name": "Sarah",
                    "message_body": "Can you confirm the next steps?",
                    "created_at": "2026-03-18 16:00",
                }
            ]
        if "SELECT service_code FROM onboarding_services" in self.last_query:
            return [{"service_code": "s3"}]
        return []


class AdminApplicationsFilterCursor(AdminBaseCursor):
    def __init__(self):
        super().__init__()
        self.last_params = None

    def execute(self, query, params=None):
        self.last_query = " ".join(query.split())
        self.last_params = params
        self.executed.append((self.last_query, params))

    def fetchone(self):
        if "COUNT(*) AS count FROM application_messages" in self.last_query:
            application_id = self.last_params[0]
            return {"count": 3 if application_id == 2 else 1}
        if "SELECT sender_role FROM application_messages" in self.last_query:
            application_id = self.last_params[0]
            return {"sender_role": "customer" if application_id == 2 else "admin"}
        return None

    def fetchall(self):
        if "FROM applications a" in self.last_query:
            return [
                {
                    "application_id": 1,
                    "organisation_name": "Northshore",
                    "contact_name": "Sarah",
                    "contact_email": "sarah@example.com",
                    "notes": "Weekly S3 review",
                    "status": "approved",
                    "created_at": "2026-03-13",
                    "onboarding_id": 10,
                    "aws_region": "eu-west-2",
                    "report_frequency": "weekly",
                    "onboarding_updated_at": "2026-03-14",
                },
                {
                    "application_id": 2,
                    "organisation_name": "BrightForge Digital",
                    "contact_name": "Priya",
                    "contact_email": "priya@example.com",
                    "notes": "RDS migration support",
                    "status": "pending",
                    "created_at": "2026-03-18",
                    "onboarding_id": 11,
                    "aws_region": "us-east-1",
                    "report_frequency": "daily",
                    "onboarding_updated_at": "2026-03-18",
                },
            ]
        if "FROM onboarding_services" in self.last_query:
            onboarding_id = self.last_params[0]
            if onboarding_id == 10:
                return [{"service_name": "Amazon S3", "service_code": "s3"}]
            return [{"service_name": "Amazon RDS", "service_code": "rds"}]
        if "FROM onboarding_report_recipients" in self.last_query:
            onboarding_id = self.last_params[0]
            if onboarding_id == 10:
                return [{"report_email": "reports@example.com"}]
            return [{"report_email": "db@example.com"}]
        return []


class AdminMessageCursor(AdminBaseCursor):
    def __init__(self, app_row, messages=None):
        super().__init__()
        self.app_row = app_row
        self.messages = messages or []
        self.last_query = ""

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


class AdminConnection:
    def __init__(self, cursors):
        self.cursors = list(cursors)
        self.committed = False
        self.cursor_calls = 0

    def cursor(self, dictionary=False):
        if self.cursor_calls < len(self.cursors):
            cursor = self.cursors[self.cursor_calls]
            self.cursor_calls += 1
            return cursor
        return AdminBaseCursor()

    def commit(self):
        self.committed = True

    def close(self):
        pass


class TestAdminRoutes(unittest.TestCase):
    def setUp(self):
        web_app.app.config["TESTING"] = True
        self.client = web_app.app.test_client()
        with self.client.session_transaction() as sess:
            sess["user_role"] = "admin"
            sess["admin_id"] = 5
            sess["admin_is_superuser"] = True

    def test_admin_update_status_rejects_bad_input(self):
        response = self.client.post("/admin/update-status", data={"application_id": "abc", "status": "wrong"})
        self.assertEqual(400, response.status_code)

    def test_admin_update_status_approved_builds_bundle(self):
        update_cursor = AdminBaseCursor()
        approval_cursor = AdminApprovalCursor()
        conn = AdminConnection([AdminBaseCursor(), update_cursor, approval_cursor])

        with patch("app.get_db_connection", return_value=conn), patch(
            "app.build_customer_bundle_data", return_value={"customer_id": "org_7"}
        ) as build_customer_bundle_data, patch("app.create_customer_bundle", return_value={"zip_filename": "org_7.zip"}) as create_customer_bundle:
            response = self.client.post("/admin/update-status", data={"application_id": "12", "status": "approved"})

        self.assertEqual(302, response.status_code)
        self.assertIn("/admin/applications", response.location)
        self.assertTrue(conn.committed)
        build_customer_bundle_data.assert_called_once()
        create_customer_bundle.assert_called_once_with({"customer_id": "org_7"})

    def test_admin_delete_admin_keeps_last_admin_account(self):
        count_cursor = AdminDeleteCursor()
        conn = AdminConnection([AdminBaseCursor(), count_cursor])

        with patch("app.get_db_connection", return_value=conn):
            response = self.client.post("/admin/admins/delete", data={"admin_id": "8"})

        self.assertEqual(302, response.status_code)
        self.assertIn("/admin/admins", response.location)
        self.assertFalse(conn.committed)

    def test_admin_dashboard_renders_counts(self):
        cursor = AdminDashboardCursor()
        conn = AdminConnection([AdminBaseCursor(), cursor])

        with patch("app.get_db_connection", return_value=conn):
            response = self.client.get("/admin")

        self.assertEqual(200, response.status_code)
        self.assertIn(b"Admin Dashboard", response.data)
        self.assertIn(b"Pending review", response.data)
        self.assertIn(b"Approved", response.data)
        self.assertIn(b"Rejected", response.data)
        self.assertIn(b"Latest applications", response.data)
        self.assertIn(b"Review queue", response.data)
        self.assertIn(b"Open review workspace", response.data)
        self.assertIn(b"Northshore", response.data)
        self.assertIn(b"Total applications: 5", response.data)

    def test_admin_applications_renders_services_and_recipients(self):
        cursor = AdminApplicationsCursor()
        conn = AdminConnection([AdminBaseCursor(), cursor])

        with patch("app.get_db_connection", return_value=conn):
            response = self.client.get("/admin/applications")

        self.assertEqual(200, response.status_code)
        self.assertIn(b"Northshore", response.data)
        self.assertIn(b"Open application", response.data)
        self.assertIn(b"Messages: 2", response.data)

    def test_admin_applications_supports_search_filter_and_sort(self):
        cursor = AdminApplicationsFilterCursor()
        conn = AdminConnection([AdminBaseCursor(), cursor])

        with patch("app.get_db_connection", return_value=conn):
            response = self.client.get(
                "/admin/applications?q=BrightForge&status=pending&service=rds&region=us-east-1&frequency=daily&sort=company_az"
            )

        self.assertEqual(200, response.status_code)
        self.assertIn(b"Showing 1 of 2 applications", response.data)
        self.assertIn(b"BrightForge Digital", response.data)
        self.assertIn(b"Open application", response.data)
        self.assertIn(b"filtered", response.data)
        self.assertNotIn(b"Northshore", response.data)

    def test_admin_application_detail_renders_details_and_messages(self):
        cursor = AdminApplicationDetailCursor()
        conn = AdminConnection([AdminBaseCursor(), cursor])

        with patch("app.get_db_connection", return_value=conn):
            response = self.client.get("/admin/applications/1")

        self.assertEqual(200, response.status_code)
        self.assertIn(b"Northshore", response.data)
        self.assertIn(b"Download deployment bundle", response.data)
        self.assertIn(b"Can you confirm the next steps?", response.data)
        self.assertIn(b"Amazon S3", response.data)

    def test_admin_download_bundle_returns_generated_zip(self):
        cursor = AdminApplicationDetailCursor(approved=True)
        conn = AdminConnection([AdminBaseCursor(), cursor])

        with patch("app.get_db_connection", return_value=conn), patch(
            "app.build_customer_bundle_data", return_value={"customer_id": "org_7"}
        ), patch("app.create_customer_bundle", return_value={"zip_filename": "org_7.zip"}), patch(
            "admin_routes.os.path.exists", return_value=True
        ), patch("admin_routes.send_from_directory", return_value="sent") as send_bundle:
            response = self.client.get("/admin/download-bundle/1")

        self.assertEqual(200, response.status_code)
        send_bundle.assert_called_once()

    def test_admin_application_messages_renders_thread(self):
        cursor = AdminMessageCursor(
            {
                "application_id": 1,
                "status": "pending",
                "organisation_name": "Northshore",
                "contact_name": "Sarah",
                "contact_email": "sarah@example.com",
            },
            messages=[
                {
                    "sender_role": "customer",
                    "sender_name": "Sarah",
                    "message_body": "Can you confirm the next steps?",
                    "created_at": "2026-03-18 16:00",
                }
            ],
        )
        conn = AdminConnection([AdminBaseCursor(), cursor])

        with patch("app.get_db_connection", return_value=conn):
            response = self.client.get("/admin/applications/1/messages")

        self.assertEqual(200, response.status_code)
        self.assertIn(b"Application #1 Conversation", response.data)
        self.assertIn(b"Can you confirm the next steps?", response.data)

    def test_admin_application_messages_posts_reply(self):
        cursor = AdminMessageCursor({"application_id": 1})
        conn = AdminConnection([AdminBaseCursor(), cursor])
        with self.client.session_transaction() as sess:
            sess["admin_email"] = "admin@example.com"

        with patch("app.get_db_connection", return_value=conn):
            response = self.client.post("/admin/applications/1/messages", data={"message_body": "We are reviewing it now."})

        self.assertEqual(302, response.status_code)
        self.assertIn("/admin/applications/1/messages", response.location)
        self.assertTrue(conn.committed)
        self.assertTrue(any("INSERT INTO application_messages" in query for query, _ in cursor.executed))

    def test_admin_update_password_invalid_admin_id_returns_400(self):
        response = self.client.post(
            "/admin/admins/update-password",
            data={"admin_id": "bad", "new_password": "password123", "confirm_password": "password123"},
        )
        self.assertEqual(400, response.status_code)

    def test_admin_delete_admin_blocks_self_delete(self):
        response = self.client.post("/admin/admins/delete", data={"admin_id": "5"})
        self.assertEqual(302, response.status_code)
        self.assertIn("/admin/admins", response.location)

    def test_non_superuser_cannot_manage_admins(self):
        with self.client.session_transaction() as sess:
            sess["admin_is_superuser"] = False

        response = self.client.get("/admin/admins")
        self.assertEqual(302, response.status_code)
        self.assertIn("/admin", response.location)


if __name__ == "__main__":
    unittest.main()
