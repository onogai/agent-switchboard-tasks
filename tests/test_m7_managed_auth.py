"""M7: managed and standalone authentication stay independently testable."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from starlette.testclient import TestClient

from task_queue.admin import list_definitions
from task_queue.web import WebConfig, create_app
from task_queue.web_auth import set_pin


class ManagedAdminAuthTests(unittest.TestCase):
    TOKEN = "managed-private-token-" + "m" * 40
    PEPPER = "pepper-" + "p" * 40
    SESSION = "central-admin-session-for-tests"

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "queue.sqlite3"
        set_pin("123456", self.PEPPER, self.db)
        self.config = WebConfig(
            db_path=self.db, session_secret="s" * 40, pin_pepper=self.PEPPER,
            managed_admin_token=self.TOKEN,
        )
        self.client = TestClient(create_app(self.config))
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def managed_headers(self, token=None, session=None):
        return {
            "Authorization": "Bearer " + (self.TOKEN if token is None else token),
            "X-Switchboard-Session-ID": self.SESSION if session is None else session,
            "X-Switchboard-Pin-Version": "1",
        }

    def test_manager_token_required_and_no_standalone_bypass(self):
        path = "/internal/queue/api/overview"
        self.assertEqual(self.client.get(path).status_code, 401)
        self.assertEqual(self.client.get(path, headers=self.managed_headers("wrong")).status_code, 401)
        self.assertEqual(self.client.get(path, headers=self.managed_headers(session="x")).status_code, 401)
        self.assertEqual(self.client.get(path, headers=self.managed_headers()).status_code, 200)
        # A managed service token never authorizes the standalone browser route.
        self.assertEqual(self.client.get("/queue/api/overview",
                                         headers=self.managed_headers()).status_code, 404)

    def test_generic_ui_api_mutation_uses_manager_session_and_token(self):
        path = "/internal/queue/ui/api/definitions"
        payload = {"title": "From generic Manager iframe", "instructions": "Run on demand"}
        self.assertEqual(self.client.post(path, json=payload).status_code, 401)
        result = self.client.post(path, json=payload, headers=self.managed_headers())
        self.assertEqual(200, result.status_code, result.text)
        self.assertEqual(payload["title"], list_definitions(self.db)[0]["title"])

    def test_managed_json_mutation_uses_service_auth_not_browser_csrf(self):
        url = "/internal/queue/api/definitions"
        payload = {"title": "Remote managed rule", "instructions": "Review daily"}
        self.assertEqual(self.client.post(url, json=payload).status_code, 401)
        created = self.client.post(url, json=payload,
                                   headers=self.managed_headers())
        self.assertEqual(created.status_code, 200, created.text)
        self.assertEqual(list_definitions(self.db)[0]["title"], payload["title"])
        # Browser CSRF requirement is unchanged for standalone endpoints.
        browser = self.client.post("/queue/api/definitions", json=payload)
        self.assertEqual(browser.status_code, 404)

    def test_proposals_and_auto_approval_use_managed_session_identity(self):
        with patch("task_queue.managed_approval.authority_valid", return_value=True):
            response = self.client.post("/internal/queue/api/auto-approval",
                                        json={"enabled": True}, headers=self.managed_headers())
            self.assertEqual(response.status_code, 200, response.text)
            self.assertTrue(response.json()["enabled"])
            status = self.client.get("/internal/queue/api/auto-approval",
                                     headers=self.managed_headers())
            self.assertEqual(status.status_code, 200)
            self.assertTrue(status.json()["enabled"])

    def test_standalone_pin_still_works_without_manager_credentials(self):
        standalone_config = WebConfig(
            db_path=self.db, session_secret="s" * 40, pin_pepper=self.PEPPER)
        with TestClient(create_app(standalone_config)) as standalone:
            self.assertEqual(standalone.get("/queue/api/overview").status_code, 401)
            csrf = standalone.get("/queue/api/session").json()["csrf_token"]
            login = standalone.post("/queue/api/login", json={"pin": "123456"},
                                    headers={"X-CSRF-Token": csrf})
            self.assertEqual(login.status_code, 200, login.text)
            self.assertEqual(standalone.get("/queue/api/overview").status_code, 200)
            # Standalone never accepts manager credentials.
            self.assertEqual(standalone.get("/internal/queue/api/overview",
                              headers=self.managed_headers()).status_code, 404)
        # The managed app never exposes a standalone login, even if a PIN exists.
        self.assertEqual(self.client.get("/queue/api/session").status_code, 404)
        self.assertEqual(self.client.post("/queue/api/login",
                         json={"pin": "123456"}).status_code, 404)

    def test_managed_mode_needs_no_local_pin_or_session_keys(self):
        app = create_app(WebConfig(db_path=self.db, managed_admin_token=self.TOKEN))
        with TestClient(app) as client:
            self.assertEqual(client.get("/internal/queue/api/overview",
                             headers=self.managed_headers()).status_code, 200)
            self.assertEqual(client.get("/queue/api/login").status_code, 404)

    def test_no_managed_endpoint_without_explicit_token(self):
        config = WebConfig(db_path=self.db, session_secret="s" * 40,
                           pin_pepper=self.PEPPER)
        standalone = TestClient(create_app(config))
        self.assertEqual(standalone.get("/internal/queue/api/overview",
                         headers=self.managed_headers()).status_code, 404)
        with self.assertRaises(RuntimeError):
            create_app(WebConfig(db_path=self.db, session_secret="s" * 40,
                                 pin_pepper=self.PEPPER, managed_admin_token="short"))


if __name__ == "__main__":
    unittest.main()
