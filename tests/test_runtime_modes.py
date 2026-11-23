"""Managed and standalone compose use the same one-process Queue runtime."""
import os
import unittest
from unittest.mock import patch

from task_queue.runtime import create_runtime_app


class RuntimeModeTests(unittest.TestCase):
    def test_managed_runtime_has_only_private_manager_routes(self):
        with patch.dict(os.environ, {
            "TASKS_ADMIN_TOKEN": "t" * 40,
            "QUEUE_WEB_SESSION_SECRET": "",
            "QUEUE_WEB_PIN_PEPPER": "",
        }):
            app = create_runtime_app()
        paths = {route.path for route in app.routes}
        self.assertIn("/internal/queue/api/overview", paths)
        self.assertIn("/internal/queue/ui/api/overview", paths)
        self.assertNotIn("/queue/api/overview", paths)
        self.assertIn("", paths)  # FastMCP root mount

    def test_standalone_runtime_has_session_protected_web_routes(self):
        with patch.dict(os.environ, {
            "TASKS_ADMIN_TOKEN": "",
            "QUEUE_WEB_SESSION_SECRET": "s" * 40,
            "QUEUE_WEB_PIN_PEPPER": "p" * 40,
        }):
            app = create_runtime_app()
        paths = {route.path for route in app.routes}
        self.assertIn("/queue/api/overview", paths)
        self.assertNotIn("/internal/queue/api/overview", paths)
        self.assertNotIn("/internal/queue/ui/api/overview", paths)
        self.assertIn("", paths)

    def test_standalone_requires_secrets(self):
        with patch.dict(os.environ, {
            "TASKS_ADMIN_TOKEN": "",
            "QUEUE_WEB_SESSION_SECRET": "",
            "QUEUE_WEB_PIN_PEPPER": "",
        }):
            with self.assertRaises(RuntimeError):
                create_runtime_app()


if __name__ == "__main__":
    unittest.main()
