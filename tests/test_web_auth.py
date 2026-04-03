import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from datetime import timedelta

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = PROJECT_ROOT / "flaskAPP" / "web"
if str(WEB_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_DIR))

import app as web_app


class FakeCursor:
    def execute(self, query, params=None):
        self.last_query = " ".join(query.split())

    def fetchone(self):
        return {"Field": "is_superuser"}

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

    def test_login_page_redirects_customer_session_to_dashboard(self):
        with self.client.session_transaction() as sess:
            sess["user_role"] = "customer"
        response = self.client.get("/login")
        self.assertEqual(302, response.status_code)
        self.assertIn("/customer/dashboard", response.location)

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
            "is_superuser": True,
        }

        with patch("app.get_db_connection", return_value=fake_conn), patch(
            "app.find_account_by_email", return_value=account
        ):
            response = self.client.post("/login", data={"email": "admin@example.com", "password": "password123"})

        self.assertEqual(403, response.status_code)
        self.assertIn(b"This admin account is inactive.", response.data)

    def test_login_invalid_credentials_returns_401(self):
        fake_conn = FakeConnection()
        with patch("app.get_db_connection", return_value=fake_conn), patch(
            "app.find_account_by_email", return_value=None
        ):
            response = self.client.post("/login", data={"email": "nope@example.com", "password": "wrongpass"})

        self.assertEqual(401, response.status_code)
        self.assertIn(b"Invalid email or password.", response.data)

    def test_forgot_password_page_redirects_customer_session(self):
        with self.client.session_transaction() as sess:
            sess["user_role"] = "customer"
        response = self.client.get("/forgot-password")
        self.assertEqual(302, response.status_code)
        self.assertIn("/customer/dashboard", response.location)

    def test_forgot_password_requires_email(self):
        response = self.client.post("/forgot-password", data={"email": ""})
        self.assertEqual(400, response.status_code)
        self.assertIn(b"Email is required.", response.data)

    def test_forgot_password_lookup_not_found(self):
        fake_conn = FakeConnection()
        with patch("app.get_db_connection", return_value=fake_conn), patch(
            "app.find_account_by_email", return_value=None
        ):
            response = self.client.post("/forgot-password", data={"email": "missing@example.com"})

        self.assertEqual(404, response.status_code)
        self.assertIn(b"Cannot find an account with this email.", response.data)

    def test_forgot_password_short_password_rejected(self):
        fake_conn = FakeConnection()
        account = {
            "user_role": "admin",
            "account_id": 1,
            "email": "admin@example.com",
            "display_name": "Admin",
            "password_hash": "old",
            "is_active": True,
            "is_superuser": True,
        }
        with patch("app.get_db_connection", return_value=fake_conn), patch(
            "app.find_account_by_email", return_value=account
        ):
            with self.client.session_transaction() as sess:
                sess["password_reset"] = {
                    "email": "admin@example.com",
                    "token": "token-123",
                    "expires_at": (web_app.utc_now() + timedelta(minutes=15)).isoformat(),
                }
            response = self.client.post(
                "/forgot-password/reset",
                data={"email": "admin@example.com", "password": "short", "confirm_password": "short", "reset_token": "token-123"},
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
            "is_superuser": True,
        }
        with patch("app.get_db_connection", return_value=fake_conn), patch(
            "app.find_account_by_email", return_value=account
        ):
            with self.client.session_transaction() as sess:
                sess["password_reset"] = {
                    "email": "admin@example.com",
                    "token": "token-123",
                    "expires_at": (web_app.utc_now() + timedelta(minutes=15)).isoformat(),
                }
            response = self.client.post(
                "/forgot-password/reset",
                data={
                    "email": "admin@example.com",
                    "password": "newpassword123",
                    "confirm_password": "different123",
                    "reset_token": "token-123",
                },
            )
        self.assertEqual(400, response.status_code)
        self.assertIn(b"Passwords do not match.", response.data)

    def test_forgot_password_lookup_creates_reset_session(self):
        fake_conn = FakeConnection()
        account = {
            "user_role": "admin",
            "account_id": 1,
            "email": "admin@example.com",
            "display_name": "Admin",
            "password_hash": "old",
            "is_active": True,
            "is_superuser": True,
        }
        with patch("app.get_db_connection", return_value=fake_conn), patch(
            "app.find_account_by_email", return_value=account
        ), patch("app.send_verification_code"):
            response = self.client.post("/forgot-password", data={"email": "admin@example.com"})

        self.assertEqual(302, response.status_code)
        self.assertIn("/forgot-password/verify", response.location)
        with self.client.session_transaction() as sess:
            self.assertEqual("admin@example.com", sess["password_reset_verification"]["email"])
            self.assertTrue(sess["password_reset_verification"]["code"])

    def test_forgot_password_verify_rejected_without_valid_session(self):
        fake_conn = FakeConnection()
        account = {
            "user_role": "admin",
            "account_id": 1,
            "email": "admin@example.com",
            "display_name": "Admin",
            "password_hash": "old",
            "is_active": True,
            "is_superuser": True,
        }
        with patch("app.get_db_connection", return_value=fake_conn), patch(
            "app.find_account_by_email", return_value=account
        ):
            response = self.client.post(
                "/forgot-password/verify",
                data={
                    "action": "verify",
                    "verification_code": "wrong-token",
                },
            )

        self.assertEqual(302, response.status_code)
        self.assertIn("/forgot-password", response.location)

    def test_forgot_password_verify_rejects_wrong_code_with_400(self):
        with self.client.session_transaction() as sess:
            sess["password_reset_verification"] = {
                "email": "admin@example.com",
                "code": "123456",
                "expires_at": (web_app.utc_now() + timedelta(minutes=15)).isoformat(),
            }

        response = self.client.post(
            "/forgot-password/verify",
            data={"action": "verify", "verification_code": "999999"},
        )

        self.assertEqual(400, response.status_code)
        self.assertIn(b"Verification code is incorrect.", response.data)

    def test_forgot_password_reset_page_redirects_when_account_missing(self):
        fake_conn = FakeConnection()
        with self.client.session_transaction() as sess:
            sess["password_reset"] = {
                "email": "missing@example.com",
                "token": "token-123",
                "expires_at": (web_app.utc_now() + timedelta(minutes=15)).isoformat(),
            }

        with patch("app.get_db_connection", return_value=fake_conn), patch(
            "app.find_account_by_email", return_value=None
        ):
            response = self.client.get("/forgot-password/reset")

        self.assertEqual(302, response.status_code)
        self.assertIn("/forgot-password", response.location)

    def test_forgot_password_reset_success(self):
        fake_conn = FakeConnection()
        account = {
            "user_role": "admin",
            "account_id": 1,
            "email": "admin@example.com",
            "display_name": "Admin",
            "password_hash": "old",
            "is_active": True,
            "is_superuser": True,
        }

        with patch("app.get_db_connection", return_value=fake_conn), patch(
            "app.find_account_by_email", return_value=account
        ), patch("app.update_account_password") as update_password:
            with self.client.session_transaction() as sess:
                sess["password_reset"] = {
                    "email": "admin@example.com",
                    "token": "token-123",
                    "expires_at": (web_app.utc_now() + timedelta(minutes=15)).isoformat(),
                }
            response = self.client.post(
                "/forgot-password/reset",
                data={
                    "email": "admin@example.com",
                    "password": "newpassword123",
                    "confirm_password": "newpassword123",
                    "reset_token": "token-123",
                },
            )

        self.assertEqual(200, response.status_code)
        self.assertIn(b"Password updated. You can now sign in with your new password.", response.data)
        update_password.assert_called_once()
        self.assertTrue(fake_conn.committed)

    def test_forgot_password_verify_code_redirects_to_reset(self):
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
        ), patch("app.send_verification_code"):
            self.client.post("/forgot-password", data={"email": "admin@example.com"})

        with self.client.session_transaction() as sess:
            code = sess["password_reset_verification"]["code"]

        response = self.client.post(
            "/forgot-password/verify",
            data={"action": "verify", "verification_code": code},
        )
        self.assertEqual(302, response.status_code)
        self.assertIn("/forgot-password/reset", response.location)

    def test_logout_and_admin_alias_routes_redirect(self):
        response = self.client.get("/admin/login")
        self.assertEqual(302, response.status_code)
        self.assertIn("/login", response.location)

        response = self.client.get("/admin/logout")
        self.assertEqual(302, response.status_code)
        self.assertIn("/logout", response.location)

        with self.client.session_transaction() as sess:
            sess["user_role"] = "admin"
            sess["admin_id"] = 1

        response = self.client.get("/logout")
        self.assertEqual(302, response.status_code)
        self.assertIn("/login", response.location)
        with self.client.session_transaction() as sess:
            self.assertNotIn("user_role", sess)

if __name__ == "__main__":
    unittest.main()
