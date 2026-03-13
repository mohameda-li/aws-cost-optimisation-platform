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

    def execute(self, query, params=None):
        self.executed.append((" ".join(query.split()), params))

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
                "status": "approved",
                "created_at": "2026-03-13",
            }
        ]


class AdminApplicationsCursor(AdminBaseCursor):
    def __init__(self):
        super().__init__()
        self.fetchall_values = iter(
            [
                [{"application_id": 1, "onboarding_id": 10, "organisation_name": "Northshore"}],
                [{"service_name": "Amazon S3", "service_code": "s3"}],
                [{"report_email": "reports@example.com"}],
            ]
        )

    def fetchall(self):
        return next(self.fetchall_values)


class AdminConnection:
    def __init__(self, cursors):
        self.cursors = list(cursors)
        self.committed = False

    def cursor(self, dictionary=False):
        return self.cursors.pop(0)

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

    def test_admin_update_status_rejects_bad_input(self):
        response = self.client.post("/admin/update-status", data={"application_id": "abc", "status": "wrong"})
        self.assertEqual(400, response.status_code)

    def test_admin_update_status_approved_builds_bundle(self):
        update_cursor = AdminBaseCursor()
        approval_cursor = AdminApprovalCursor()
        conn = AdminConnection([update_cursor, approval_cursor])

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
        conn = AdminConnection([count_cursor])

        with patch("app.get_db_connection", return_value=conn):
            response = self.client.post("/admin/admins/delete", data={"admin_id": "8"})

        self.assertEqual(302, response.status_code)
        self.assertIn("/admin/admins", response.location)
        self.assertFalse(conn.committed)

    def test_admin_dashboard_renders_counts(self):
        cursor = AdminDashboardCursor()
        conn = AdminConnection([cursor])

        with patch("app.get_db_connection", return_value=conn):
            response = self.client.get("/admin")

        self.assertEqual(200, response.status_code)
        self.assertIn(b"Admin Dashboard", response.data)
        self.assertIn(b"Admins:</b> 2", response.data)
        self.assertIn(b"Applications:</b> 5", response.data)
        self.assertIn(b"Onboardings:</b> 4", response.data)

    def test_admin_applications_renders_services_and_recipients(self):
        cursor = AdminApplicationsCursor()
        conn = AdminConnection([cursor])

        with patch("app.get_db_connection", return_value=conn):
            response = self.client.get("/admin/applications")

        self.assertEqual(200, response.status_code)
        self.assertIn(b"Northshore", response.data)
        self.assertIn(b"Amazon S3", response.data)
        self.assertIn(b"reports@example.com", response.data)

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


if __name__ == "__main__":
    unittest.main()
