import unittest
from unittest.mock import patch

from dashboard import app as dashboard_app


class OwnerPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        dashboard_app.app.config["TESTING"] = True
        dashboard_app.SUPER_ADMIN_USER_IDS.add("123")
        dashboard_app.ALLOWED_USER_IDS.add("123")

    def setUp(self):
        self.client = dashboard_app.app.test_client()
        with self.client.session_transaction() as session:
            session["user_id"] = "123"
            session["username"] = "owner"

    def test_owner_pages_require_super_admin_session(self):
        response = self.client.get("/owner")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Owner Panel", response.data)

    def test_bot_control_is_owner_only(self):
        response = self.client.get("/control")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Bot Control", response.data)

    def test_bot_control_rejects_server_only_user(self):
        with self.client.session_transaction() as session:
            session["user_id"] = "456"
        response = self.client.get("/control")
        self.assertEqual(response.status_code, 302)

    def test_security_headers_are_present(self):
        response = self.client.get("/health")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")

    def test_owner_post_requires_csrf_token(self):
        response = self.client.post("/owner/servers/refresh")
        self.assertEqual(response.status_code, 400)

    def test_owner_refresh_accepts_session_csrf_token(self):
        with self.client.get("/owner"):
            pass
        with self.client.session_transaction() as session:
            csrf_token = session["csrf_token"]
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

    def test_server_selection_rejects_unadministered_server(self):
        with self.client.session_transaction() as session:
            session["administered_guilds"] = [{"id": "456", "name": "Allowed"}]
        response = self.client.get("/select-server/999")
        self.assertEqual(response.status_code, 302)

    def test_server_selection_accepts_administered_server(self):
        # Being an admin of the server on Discord is NOT enough on its own -
        # access is granted by actual registry approval, matching the same
        # owner_discord_id as the logged-in session. This is deliberate:
        # someone could administer a Discord server that was never approved
        # (or was denied), and that must never be sufficient to reach its
        # dashboard data.
        entry = dashboard_app.reg.request_access(456, "Allowed", 123, "owner")
        dashboard_app.reg.decide(entry.id, approve=True, decided_by=123)

        response = self.client.get("/select-server/456")
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as session:
            self.assertEqual(session["guild_id"], 456)

    def test_server_selection_rejects_administered_but_unapproved_server(self):
        # The actual gap this guards against: session["administered_guilds"]
        # reflects raw Discord admin status, unrelated to registry approval.
        # A guild present ONLY in that list (no approved registry entry)
        # must be rejected.
        with self.client.session_transaction() as session:
            session["administered_guilds"] = [{"id": "789", "name": "Not Approved"}]
        response = self.client.get("/select-server/789")
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as session:
            self.assertNotEqual(session.get("guild_id"), 789)


if __name__ == "__main__":
    unittest.main()
