"""Disposable tests for the offline Queue add-on migration."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from scripts.migrate_addon_state import migrate, snapshot, MigrationError


def make_queue_db(path: Path, value: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE task_definitions(id TEXT PRIMARY KEY);
            CREATE TABLE task_instances(id TEXT PRIMARY KEY);
            CREATE TABLE task_attempts(id INTEGER PRIMARY KEY);
            CREATE TABLE task_events(id INTEGER PRIMARY KEY);
            CREATE TABLE task_change_proposals(id TEXT PRIMARY KEY);
            PRAGMA user_version=2;
        """)
        if value:
            db.execute("INSERT INTO task_definitions(id) VALUES (?)", (value,))


class QueueMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.legacy = self.root / "legacy"
        self.legacy.mkdir()
        self.addon = self.root / "addon" / "tasks"
        (self.addon / "state" / "data").mkdir(parents=True)
        (self.addon / "state" / "secrets").mkdir()
        self.token = "a" * 64
        self.old_env = self.root / ".env.production"
        self.old_env.write_text(
            f"TASKS_STATE_ROOT={self.legacy}\nTASKS_ADMIN_TOKEN={self.token}\n"
        )
        make_queue_db(self.legacy / "queue.sqlite3", "live-rule")
        make_queue_db(self.addon / "state" / "data" / "queue.sqlite3", "")
        (self.addon / "state" / "secrets" / "admintoken").write_text("b" * 64)
        (self.addon / "config.env").write_text(
            "SWITCHBOARD_ADDON_SECRET_ADMINTOKEN=" + "b" * 64 + "\n"
        )
        self.metadata = {
            "schema": "2", "target": "production", "addon_id": "queue",
            "instance": "tasks", "source_id": "tasks", "service": "queue",
            "services": ["queue"], "staged_replacement": {
                "old_url": "http://tasks_mcp:8771/mcp", "revision": 0,
            },
        }
        (self.addon / "installation.json").write_text(json.dumps(self.metadata))

    def test_preview_does_not_change_any_state_or_print_secret(self):
        before = (self.addon / "config.env").read_text()
        result = migrate(self.old_env, self.addon)
        self.assertEqual(result["counts"]["task_definitions"], 1)
        self.assertNotIn(self.token, json.dumps(result))
        self.assertEqual((self.addon / "config.env").read_text(), before)
        self.assertFalse((self.addon / "migration-backups").exists())

    def test_forward_copy_uses_sqlite_backup_and_keeps_legacy_untouched(self):
        with patch("scripts.migrate_addon_state.assert_stopped_queue_containers"):
            result = migrate(self.old_env, self.addon, commit=True)
        target = self.addon / "state" / "data" / "queue.sqlite3"
        self.assertEqual(snapshot(target)["counts"]["task_definitions"], 1)
        self.assertEqual(snapshot(self.legacy / "queue.sqlite3")["counts"]["task_definitions"], 1)
        self.assertEqual(
            (self.addon / "state" / "secrets" / "admintoken").read_text(),
            self.token + "\n",
        )
        self.assertIn(self.token, (self.addon / "config.env").read_text())
        backups = Path(result["backup_dir"])
        self.assertTrue((backups / "source.sqlite3").exists())
        self.assertTrue((backups / "previous-queue.sqlite3").exists())
        self.assertTrue((backups / "previous-config.env").exists())
        self.assertNotIn(self.token, json.dumps(result))

    def test_reverse_copy_preserves_new_task_history(self):
        with patch("scripts.migrate_addon_state.assert_stopped_queue_containers"):
            migrate(self.old_env, self.addon, commit=True)
        target = self.addon / "state" / "data" / "queue.sqlite3"
        with sqlite3.connect(target) as db:
            db.execute("INSERT INTO task_definitions(id) VALUES ('post-cutover')")
        info = dict(self.metadata)
        info.pop("staged_replacement")
        info["handoff_from_url"] = "http://tasks_mcp:8771/mcp"
        (self.addon / "installation.json").write_text(json.dumps(info))
        with patch("scripts.migrate_addon_state.assert_stopped_queue_containers"):
            migrate(self.old_env, self.addon, reverse=True, commit=True)
        self.assertEqual(
            snapshot(self.legacy / "queue.sqlite3")["counts"]["task_definitions"], 2
        )

    def test_docker_preflight_failure_leaves_database_untouched(self):
        with patch("scripts.migrate_addon_state.assert_stopped_queue_containers",
                   side_effect=MigrationError("still running")):
            with self.assertRaisesRegex(MigrationError, "still running"):
                migrate(self.old_env, self.addon, commit=True)
        self.assertEqual(
            snapshot(self.addon / "state" / "data" / "queue.sqlite3")["counts"]["task_definitions"],
            0,
        )

    def test_refuses_wrong_schema_and_secret(self):
        with sqlite3.connect(self.legacy / "queue.sqlite3") as db:
            db.execute("PRAGMA user_version=4")
        with self.assertRaisesRegex(MigrationError, "schema v2"):
            migrate(self.old_env, self.addon)
        with sqlite3.connect(self.legacy / "queue.sqlite3") as db:
            db.execute("PRAGMA user_version=2")
        self.old_env.write_text(
            f"TASKS_STATE_ROOT={self.legacy}\nTASKS_ADMIN_TOKEN=short\n"
        )
        with self.assertRaisesRegex(MigrationError, "token"):
            migrate(self.old_env, self.addon)


if __name__ == "__main__":
    unittest.main()
