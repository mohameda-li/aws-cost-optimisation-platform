import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = PROJECT_ROOT / "flaskAPP" / "web"
if str(WEB_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_DIR))

import app as web_app


class FakeCursor:
    def close(self):
        pass


class FakeConnection:
    def __init__(self):
        self.committed = False

    def cursor(self, dictionary=True):
        return FakeCursor()

    def commit(self):
        self.committed = True

    def close(self):
        pass


class TestWebAuth(unittest.TestCase):
    def setUp(self):
        web_app.app.config["TESTING"] = True
        self.client = web_app.app.test_client()

    def test_login_requires_email_and_password(self):
        response = self.client.post("/login", data={"email": "", "password": ""})
        self.assertEqual(400, response.status_code)
        self.assertIn(b"Email and password are required.", response.data)

    def test_login_page_redirects_by_session_role(self):
        with self.client.session_transaction() as sess:
            sess["user_role"] = "admin"
        response = self.client.get("/login")
        self.assertEqual(302, response.status_code)
        self.assertIn("/admin", response.location)

    def test_customer_login_success(self):
        fake_conn = FakeConnection()
        account = {
            "user_role": "customer",
            "account_id": 42,
            "organisation_id": 7,
            "email": "customer@example.com",
            "display_name": "Customer Name",
            "password_hash": "irrelevant",
        }

        with patch("app.get_db_connection", return_value=fake_conn), patch(
            "app.find_account_by_email", return_value=account
        ), patch("app.verify_password", return_value=True):
            response = self.client.post(
                "/login",
                data={"email": "customer@example.com", "password": "password123"},
            )

        self.assertEqual(302, response.status_code)
        self.assertIn("/customer/dashboard", response.location)

    def test_admin_login_inactive_account(self):
        fake_conn = FakeConnection()
        account = {
            "user_role": "admin",
            "account_id": 1,
            "email": "admin@example.com",
            "display_name": "Admin",
            "password_hash": "irrelevant",
            "is_active": False,
        }

        with patch("app.get_db_connection", return_value=fake_conn), patch(
            "app.find_account_by_email", return_value=account
        ):
            response = self.client.post("/login", data={"email": "admin@example.com", "password": "password123"})

        self.assertEqual(403, response.status_code)
        self.assertIn(b"This admin account is inactive.", response.data)

    def test_forgot_password_lookup_not_found(self):
        fake_conn = FakeConnection()
        with patch("app.get_db_connection", return_value=fake_conn), patch(
            "app.find_account_by_email", return_value=None
        ):
            response = self.client.post("/forgot-password", data={"email": "missing@example.com", "step": "lookup"})

        self.assertEqual(404, response.status_code)
        self.assertIn(b"No account was found for that email address.", response.data)

    def test_forgot_password_short_password_rejected(self):
        fake_conn = FakeConnection()
        account = {
            "user_role": "admin",
            "account_id": 1,
            "email": "admin@example.com",
            "display_name": "Admin",
            "password_hash": "old",
            "is_active": True,
        }
        with patch("app.get_db_connection", return_value=fake_conn), patch(
            "app.find_account_by_email", return_value=account
        ):
            response = self.client.post(
                "/forgot-password",
                data={"email": "admin@example.com", "step": "reset", "password": "short", "confirm_password": "short"},
            )
        self.assertEqual(400, response.status_code)
        self.assertIn(b"Password must be at least 8 characters long.", response.data)

    def test_forgot_password_mismatch_rejected(self):
        fake_conn = FakeConnection()
        account = {
            "user_role": "admin",
            "account_id": 1,
            "email": "admin@example.com",
            "display_name": "Admin",
            "password_hash": "old",
            "is_active": True,
        }
        with patch("app.get_db_connection", return_value=fake_conn), patch(
            "app.find_account_by_email", return_value=account
        ):
            response = self.client.post(
                "/forgot-password",
                data={
                    "email": "admin@example.com",
                    "step": "reset",
                    "password": "newpassword123",
                    "confirm_password": "different123",
                },
            )
        self.assertEqual(400, response.status_code)
        self.assertIn(b"Passwords do not match.", response.data)

    def test_forgot_password_reset_success(self):
        fake_conn = FakeConnection()
        account = {
            "user_role": "admin",
            "account_id": 1,
            "email": "admin@example.com",
            "display_name": "Admin",
            "password_hash": "old",
            "is_active": True,
        }

        with patch("app.get_db_connection", return_value=fake_conn), patch(
            "app.find_account_by_email", return_value=account
        ), patch("app.update_account_password") as update_password:
            response = self.client.post(
                "/forgot-password",
                data={
                    "email": "admin@example.com",
                    "step": "reset",
                    "password": "newpassword123",
                    "confirm_password": "newpassword123",
                },
            )

        self.assertEqual(200, response.status_code)
        self.assertIn(b"Password updated. You can now sign in with your new password.", response.data)
        update_password.assert_called_once()
        self.assertTrue(fake_conn.committed)


if __name__ == "__main__":
    unittest.main()
