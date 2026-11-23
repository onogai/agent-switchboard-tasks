"""Queue independently serves standalone and Manager-hosted UI assets."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from starlette.testclient import TestClient

from task_queue.web import WebConfig, create_app


class QueueUiOwnershipTests(unittest.TestCase):
    TOKEN = "test-service-token-" + "t" * 40
    SESSION = "manager-session-id-for-queue-assets"

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.build = root / "managed-dist"
        (self.build / "assets").mkdir(parents=True)
        (self.build / "index.html").write_text(
            '<!doctype html><script src="/admin/addon-ui/tasks/assets/app.js"></script>')
        (self.build / "assets" / "app.js").write_text("/* owned by queue */")
        self.managed = TestClient(create_app(WebConfig(
            db_path=root / "queue.sqlite3", managed_static_dir=self.build,
            managed_admin_token=self.TOKEN,
        )))
        self.managed.__enter__()
        self.addCleanup(self.managed.__exit__, None, None, None)

    def headers(self, token=None, session=None):
        return {
            "Authorization": "Bearer " + (self.TOKEN if token is None else token),
            "X-Switchboard-Session-ID": self.SESSION if session is None else session,
        }

    def test_ui_requires_private_auth_even_for_static_assets(self):
        for path in ("/internal/queue/ui", "/internal/queue/ui/",
                     "/internal/queue/ui/assets/app.js",
                     "/internal/queue/ui/rules/new"):
            self.assertEqual(self.managed.get(path).status_code, 401, path)
            self.assertEqual(self.managed.get(path, headers=self.headers("invalid")).status_code, 401)
            self.assertEqual(self.managed.get(path, headers=self.headers(session="x")).status_code, 401)

    def test_manager_can_fetch_owned_js_html_and_spa_routes(self):
        for path in ("/internal/queue/ui", "/internal/queue/ui/",
                     "/internal/queue/ui/rules/new"):
            result = self.managed.get(path, headers=self.headers())
            self.assertEqual(result.status_code, 200, path)
            self.assertIn("/admin/addon-ui/tasks/assets/app.js", result.text)
            self.assertEqual(result.headers["cache-control"], "no-store")
        asset = self.managed.get("/internal/queue/ui/assets/app.js",
                                 headers=self.headers())
        self.assertEqual(asset.status_code, 200)
        self.assertIn("owned by queue", asset.text)

    def test_ui_api_uses_same_private_manager_auth(self):
        api = "/internal/queue/ui/api/overview"
        self.assertEqual(401, self.managed.get(api).status_code)
        self.assertEqual(401, self.managed.get(api, headers=self.headers("wrong")).status_code)
        result = self.managed.get(api, headers=self.headers())
        self.assertEqual(200, result.status_code, result.text)
        self.assertIn("counts", result.json())

    def test_hidden_missing_or_nested_assets_are_not_exposed(self):
        for path in ("/internal/queue/ui/assets/.env",
                     "/internal/queue/ui/assets/nested/script.js",
                     "/internal/queue/ui/assets/missing.js"):
            self.assertEqual(self.managed.get(path, headers=self.headers()).status_code, 404, path)
        self.assertEqual(self.managed.get("/queue/", headers=self.headers()).status_code, 404)

    def test_standalone_has_no_manager_private_ui(self):
        root = Path(self.temp.name)
        standalone_build = root / "standalone"
        standalone_build.mkdir()
        (standalone_build / "index.html").write_text("standalone")
        app = create_app(WebConfig(db_path=root / "queue.sqlite3",
                                  session_secret="s" * 40,
                                  pin_pepper="p" * 40,
                                  static_dir=standalone_build))
        with TestClient(app) as client:
            self.assertEqual(client.get("/internal/queue/ui",
                             headers=self.headers()).status_code, 404)
            self.assertEqual(client.get("/queue/").status_code, 200)


if __name__ == "__main__":
    unittest.main()
