import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = PROJECT_ROOT / "flaskAPP" / "web"
if str(WEB_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_DIR))

import app as web_app


class TestSmoke(unittest.TestCase):
    def test_homepage_renders(self):
        web_app.app.config["TESTING"] = True
        client = web_app.app.test_client()
        response = client.get("/")
        self.assertEqual(200, response.status_code)
        self.assertIn(b"FinOps", response.data)


if __name__ == "__main__":
    unittest.main()
