"""M8 central PIN epoch revocation and standalone auto-approval semantics."""

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from starlette.testclient import TestClient

from task_queue.managed_approval import managed_session, auto_approval_authorized
from task_queue.proposals import auto_approval_state, set_auto_approval, submit_proposal
from task_queue.web import WebConfig, create_app


class ManagedEpochTests(unittest.TestCase):
    TOKEN = "managed-private-secret-" + "t" * 40
    SESSION = "an-authenticated-manager-browser-session"
    HEADERS = {
        "Authorization": "Bearer " + TOKEN,
        "X-Switchboard-Session-ID": SESSION,
        "X-Switchboard-Pin-Version": "7",
    }

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "queue.sqlite3"
        self.client = TestClient(create_app(WebConfig(
            db_path=self.db, managed_admin_token=self.TOKEN)))
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def _propose(self, key):
        return submit_proposal("create_rule",
                               {"title": "Example " + key, "instructions": "Review"},
                               None, None, "agent", key, self.db)

    def test_pin_rotation_revokes_automatic_approval_but_keeps_manual_proposals(self):
        with patch("task_queue.managed_approval.authority_valid", return_value=True):
            enabled = self.client.post("/internal/queue/api/auto-approval",
                json={"enabled": True}, headers=self.HEADERS)
            self.assertEqual(enabled.status_code, 200, enabled.text)
            self.assertTrue(enabled.json()["enabled"])
            # An automatically decided proposal is safe while the PIN epoch is current.
            self.assertEqual(self._propose("before")["status"], "approved")

        with patch("task_queue.managed_approval.authority_valid", return_value=False):
            # Manager PIN changed: no callback can authorize the old version.
            self.assertFalse(auto_approval_state(self.db)["enabled"])
            self.assertEqual(self._propose("after")["status"], "pending")
            self.assertFalse(self.client.get("/internal/queue/api/auto-approval",
                headers=self.HEADERS).json()["enabled"])
            retried = self.client.post("/internal/queue/api/auto-approval",
                json={"enabled": True}, headers=self.HEADERS)
            self.assertEqual(retried.status_code, 400)
            self.assertIn("authority", retried.text)

    def test_new_manager_epoch_replaces_old_unexpired_approval(self):
        with patch("task_queue.managed_approval.authority_valid", return_value=True):
            self.client.post("/internal/queue/api/auto-approval",
                json={"enabled": True}, headers=self.HEADERS)
            renewed = dict(self.HEADERS)
            renewed["X-Switchboard-Pin-Version"] = "8"
            response = self.client.post("/internal/queue/api/auto-approval",
                json={"enabled": True}, headers=renewed)
            self.assertEqual(response.status_code, 200, response.text)
            with __import__("sqlite3").connect(self.db) as connection:
                owner = connection.execute(
                    "SELECT auto_approve_session_id FROM queue_security WHERE id=1"
                ).fetchone()[0]
            self.assertEqual(owner, managed_session(self.SESSION, 8))

    def test_no_central_version_or_missing_authority_cannot_enable(self):
        no_epoch = dict(self.HEADERS)
        no_epoch.pop("X-Switchboard-Pin-Version")
        response = self.client.post("/internal/queue/api/auto-approval",
            json={"enabled": True}, headers=no_epoch)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(auto_approval_state(self.db)["enabled"])
        with patch.dict(os.environ, {
                "TASKS_ADMIN_TOKEN": self.TOKEN,
                "TASKS_AUTHORITY_URL": ""}):
            self.assertFalse(auto_approval_authorized(managed_session(self.SESSION, 7)))

    def test_leftover_standalone_lease_rejected_in_managed_worker(self):
        with patch.dict(os.environ, {}, clear=True):
            set_auto_approval(True, self.SESSION, self.db)
            self.assertEqual(self._propose("standalone")["status"], "approved")
        with patch.dict(os.environ, {"TASKS_ADMIN_TOKEN": self.TOKEN}):
            self.assertEqual(self._propose("managed")["status"], "pending")
            self.assertFalse(auto_approval_state(self.db)["enabled"])

    def test_unreachable_authority_never_falls_back_to_standalone(self):
        with patch.dict(os.environ, {
                "TASKS_ADMIN_TOKEN": self.TOKEN,
                "TASKS_AUTHORITY_URL": "http://127.0.0.1:1"}):
            self.assertFalse(auto_approval_authorized(managed_session(self.SESSION, 7)))
            self.assertFalse(auto_approval_authorized("managed:v7:bad-session"))


if __name__ == "__main__":
    unittest.main()
