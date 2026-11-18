"""React API access, queue state, and administrator mutation tests."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from starlette.testclient import TestClient

from task_queue.admin import create_definition, list_definitions, list_instances, trigger_definition
from task_queue.web import WebConfig, create_app
from task_queue.web_auth import set_pin
from task_queue.proposals import submit_proposal
from task_queue.db import open_queue_db
from task_queue.auth import admin_db_path
import sqlite3


class QueueWebTests(unittest.TestCase):
    PEPPER = "p" * 40

    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "queue.sqlite3"
        static = Path(self.directory.name) / "dist"
        static.mkdir()
        (static / "index.html").write_text('<!doctype html><div id="root"></div>')
        set_pin("012345", self.PEPPER, self.path)
        self.client = TestClient(create_app(WebConfig(
            db_path=self.path, session_secret="a" * 40, static_dir=static,
            pin_pepper=self.PEPPER)))
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.assertEqual(self.client.get("/queue/api/overview").status_code, 401)
        token = self.client.get("/queue/api/session").json()["csrf_token"]
        response = self.client.post("/queue/api/login", json={"pin": "012345"},
                                    headers={"X-CSRF-Token": token})
        self.assertEqual(response.status_code, 200, response.text)

    def token(self):
        response = self.client.get("/queue/api/session")
        self.assertEqual(response.status_code, 200)
        return response.json()["csrf_token"]

    def write(self, path, data=None, method="post", token=None):
        return getattr(self.client, method)(path, json=data or {},
            headers={"X-CSRF-Token": token or self.token()})

    def test_spa_routes_and_json_api(self):
        self.assertEqual(self.client.get("/queue/").status_code, 200)
        self.assertIn('id="root"', self.client.get("/queue/rules/new").text)
        self.assertEqual(self.client.get("/queue/api/unknown").status_code, 404)
        self.assertEqual(self.client.get("/queue/api/instances?status=unknown").status_code, 400)
        self.assertEqual(self.client.get("/queue/api/definitions/missing").status_code, 404)

    def test_anonymous_routes_are_server_protected(self):
        other = TestClient(create_app(WebConfig(
            db_path=self.path, session_secret="a" * 40,
            pin_pepper=self.PEPPER)))
        for route in ("overview", "definitions", "instances", "proposals", "auto-approval"):
            self.assertEqual(other.get(f"/queue/api/{route}").status_code, 401)
        self.assertEqual(other.post("/queue/api/proposals/missing/approve", json={}).status_code, 401)

    def test_missing_auth_configuration_fails_closed(self):
        with self.assertRaises(RuntimeError):
            create_app(WebConfig(db_path=self.path, session_secret=None,
                                 pin_pepper=self.PEPPER))
        with self.assertRaises(RuntimeError):
            create_app(WebConfig(db_path=self.path, session_secret="a" * 40,
                                 pin_pepper="CHANGE_ME_TO_RANDOM_32_PLUS_CHARACTERS"))

    def test_login_lockout_survives_client_restart_and_pin_rotation(self):
        other = TestClient(create_app(WebConfig(
            db_path=self.path, session_secret="a" * 40, pin_pepper=self.PEPPER)))
        token = other.get("/queue/api/session").json()["csrf_token"]
        for _ in range(5):
            self.assertEqual(other.post("/queue/api/login", json={"pin": "999999"},
                headers={"X-CSRF-Token": token}).status_code, 401)
        restarted = TestClient(create_app(WebConfig(
            db_path=self.path, session_secret="a" * 40, pin_pepper=self.PEPPER)))
        token = restarted.get("/queue/api/session").json()["csrf_token"]
        self.assertEqual(restarted.post("/queue/api/login", json={"pin": "012345"},
            headers={"X-CSRF-Token": token}).status_code, 401)
        with sqlite3.connect(admin_db_path(self.path)) as db:
            self.assertIsNotNone(db.execute("SELECT locked_until FROM security").fetchone()[0])
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM security_events WHERE action='pin_login_locked'"
            ).fetchone()[0], 1)
        set_pin("123456", self.PEPPER, self.path)
        self.assertFalse(self.client.get("/queue/api/session").json()["authenticated"])
        self.assertEqual(self.client.get("/queue/api/overview").status_code, 401)

    def test_proposal_approval_and_auto_toggle_require_session_and_csrf(self):
        proposal = submit_proposal("create_rule", {"title": "Review", "instructions": "Work"},
                                   None, None, "agent", "review", self.path)
        self.assertEqual(self.client.get("/queue/api/proposals?status=pending").json()["proposals"][0]["id"],
                         proposal["id"])
        self.assertEqual(self.client.post(f"/queue/api/proposals/{proposal['id']}/approve",
                                          json={}).status_code, 400)
        approved = self.write(f"/queue/api/proposals/{proposal['id']}/approve").json()
        self.assertEqual(approved["status"], "approved")
        self.assertEqual(self.write("/queue/api/auto-approval", {"enabled": True}).json()["enabled"],
                         True)
        automatic = submit_proposal("create_rule", {"title": "Automatic", "instructions": "Work"},
                                    None, None, "agent", "automatic", self.path)
        self.assertEqual(automatic["status"], "approved")
        self.assertEqual(automatic["decision_source"], "auto")
        self.assertEqual(self.write("/queue/api/auto-approval", {"enabled": False}).json()["enabled"],
                         False)

    def test_csrf_and_validation(self):
        path = "/queue/api/definitions"
        bad = self.client.post(path, json={"title": "No", "instructions": "Run"})
        self.assertEqual(bad.status_code, 400)
        self.assertIn("CSRF", bad.json()["error"])
        invalid = self.write(path, {"title": "Invalid", "instructions": "Run", "priority": 12})
        self.assertEqual(invalid.status_code, 400)
        self.assertIn("Priority", invalid.json()["error"])
        self.assertEqual(list_definitions(self.path), [])

    def test_create_edit_trigger_cancel_retry(self):
        path = "/queue/api/definitions"
        data = {"title": "Spanish news", "instructions": "<script>x</script>",
                "schedule_kind": "daily", "daily_time_local": "10:00",
                "timezone_name": "Europe/Madrid", "priority": 7,
                "interval_minutes": -1, "interval_anchor_at": "invalid"}
        response = self.write(path, data)
        self.assertEqual(response.status_code, 200, response.text)
        identifier = response.json()["id"]
        rule = self.client.get(f"{path}/{identifier}").json()
        self.assertEqual(rule["definition"]["interval_minutes"], None)
        self.assertEqual(rule["definition"]["daily_time_local"], "10:00")
        next_run = rule["definition"]["next_scheduled_at"]
        data["title"] = "Spain briefing"
        data["expected_version"] = rule["definition"]["version"]
        self.assertEqual(self.write(f"{path}/{identifier}", data, "put").status_code, 200)
        self.assertEqual(list_definitions(self.path)[0]["next_scheduled_at"], next_run)
        self.assertEqual(self.write(f"{path}/{identifier}/toggle", {"is_active": False,
            "expected_version": 2}).json()["is_active"], False)
        self.assertEqual(self.write(f"{path}/{identifier}/toggle", {"is_active": True,
            "expected_version": 3}).json()["is_active"], True)
        task_id = self.write(f"{path}/{identifier}/trigger").json()["id"]
        task = self.client.get(f"/queue/api/instances/{task_id}").json()
        self.assertEqual(task["instance"]["instructions_snapshot"], "<script>x</script>")
        self.assertEqual(self.write(f"/queue/api/instances/{task_id}/cancel").status_code, 200)
        self.assertEqual(self.write(f"/queue/api/instances/{task_id}/retry").status_code, 200)
        self.assertGreaterEqual(len(list_instances(self.path)), 3)

    def test_overview_distinguishes_future_from_claimable(self):
        identifier = create_definition("Review", "Do work", schedule_kind="interval",
                                       interval_minutes=10, db_path=self.path)
        initial = self.client.get("/queue/api/overview").json()
        self.assertEqual(initial["claimable_count"], 1)
        self.assertGreater(initial["counts"]["future"], 100)
        self.assertIsNotNone(initial["next_due_at"])
        task_id = trigger_definition(identifier, db_path=self.path)
        updated = self.client.get("/queue/api/overview").json()
        self.assertEqual(updated["claimable_count"], 2)
        self.assertIn(task_id, {row["id"] for row in updated["claimable"]})


if __name__ == "__main__":
    unittest.main()
