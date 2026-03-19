import os
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = PROJECT_ROOT / "flaskAPP" / "web"
if str(WEB_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_DIR))

from flask import Flask

from config import AppConfig, configure_logging


class TestConfig(unittest.TestCase):
    def test_app_config_marks_production_environment(self):
        previous = os.environ.get("APP_ENV")
        os.environ["APP_ENV"] = "production"
        try:
            config = AppConfig.from_env()
            self.assertTrue(config.is_production)
        finally:
            if previous is None:
                os.environ.pop("APP_ENV", None)
            else:
                os.environ["APP_ENV"] = previous

    def test_configure_logging_rejects_default_secret_in_production(self):
        app = Flask(__name__)
        app.secret_key = "dev-secret-change-later"
        config = AppConfig(
            app_env="production",
            secret_key="dev-secret-change-later",
            app_base_url="http://localhost:5050",
            smtp_host="",
            smtp_port=587,
            smtp_username="",
            smtp_password="",
            smtp_sender="",
            smtp_use_tls=True,
            db_host="127.0.0.1",
            db_port=3306,
            db_user="finops_app",
            db_password="",
            db_name="finops",
        )
        with self.assertRaises(RuntimeError):
            configure_logging(app, config)


if __name__ == "__main__":
    unittest.main()
