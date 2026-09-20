import unittest
from unittest.mock import patch

from dashboard import app as dashboard_app


class OwnerPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        dashboard_app.app.config["TESTING"] = True
        dashboard_app.SUPER_ADMIN_USER_IDS.add("123")

    def setUp(self):
        self.client = dashboard_app.app.test_client()
        with self.client.session_transaction() as session:
            session["user_id"] = "123"
            session["username"] = "owner"

    def test_owner_pages_require_super_admin_session(self):
        response = self.client.get("/owner")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Owner Panel", response.data)

    def test_owner_post_requires_csrf_token(self):
        response = self.client.post("/owner/servers/refresh")
        self.assertEqual(response.status_code, 400)

    def test_owner_refresh_accepts_session_csrf_token(self):
        with self.client.get("/owner"):
            pass
        with self.client.session_transaction() as session:
            csrf_token = session["owner_csrf_token"]
        with patch.object(dashboard_app, "refresh_discovered_servers", return_value=(2, 1)):
            response = self.client.post(
                "/owner/servers/refresh",
                data={"csrf_token": csrf_token},
            )
        self.assertEqual(response.status_code, 302)

    def test_invite_code_parses_discord_invite(self):
        self.assertEqual(dashboard_app.invite_code("https://discord.gg/example"), "example")
        self.assertIsNone(dashboard_app.invite_code(None))

    def test_health_endpoint_returns_structured_status(self):
        response = self.client.get("/health")
        self.assertIn(response.status_code, (200, 503))
        self.assertIn("status", response.get_json())


if __name__ == "__main__":
    unittest.main()
