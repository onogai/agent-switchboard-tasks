"""Tests for atomic task leasing and idempotent agent reports."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from task_queue.db import open_queue_db, transaction
from task_queue.scheduler import stamp
from task_queue.service import (QueueConflict, claim_next_task, extend_task_lease,
                           report_task_result)


NOW = datetime(2026, 11, 3, 12, tzinfo=timezone.utc)


def add_task(path: Path, name: str, priority: int = 5,
             ready_at: datetime = NOW, max_attempts: int = 3) -> None:
    with open_queue_db(path) as connection:
        with transaction(connection):
            connection.execute(
                """INSERT INTO task_definitions
                   (id, title, instructions, priority, schedule_kind,
                    max_attempts, created_at, updated_at)
                   VALUES (?, ?, ?, ?, 'manual', ?, ?, ?)""",
                (name, name, f"Do {name}.", priority, max_attempts,
                 stamp(NOW), stamp(NOW)),
            )
            connection.execute(
                """INSERT INTO task_instances
                   (id, definition_id, definition_version, occurrence_key,
                    title_snapshot, instructions_snapshot, priority_snapshot,
                    scheduled_at, ready_at, window_start_at, origin,
                    miss_policy_snapshot, lease_seconds_snapshot,
                    max_attempts_snapshot, status, created_at, updated_at)
                   VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, 'manual',
                           'run_late', 1800, ?, 'ready', ?, ?)""",
                (name + "-instance", name, name + "-occurrence", name,
                 f"Do {name}.", priority, stamp(ready_at), stamp(ready_at), stamp(ready_at),
                 max_attempts,
                 stamp(NOW), stamp(NOW)),
            )


class QueueServiceTests(unittest.TestCase):
    def test_priority_leasing_success_and_idempotent_report(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "queue.sqlite3"
            add_task(path, "low", priority=1)
            add_task(path, "high", priority=9)
            first = claim_next_task(path, NOW)["task"]
            self.assertEqual(first["task_id"], "high-instance")
            self.assertEqual(first["attempt"], 1)
            self.assertEqual(claim_next_task(path, NOW)["task"]["task_id"],
                             "low-instance")
            self.assertIsNone(claim_next_task(path, NOW)["task"])
            response = report_task_result(first["task_id"], first["lease_token"],
                                          "succeeded", result="done", db_path=path,
                                          now=NOW)
            self.assertEqual(response["status"], "succeeded")
            self.assertEqual(report_task_result(
                first["task_id"], first["lease_token"], "succeeded",
                result="done", db_path=path, now=NOW), response)
            with self.assertRaises(QueueConflict):
                report_task_result(first["task_id"], first["lease_token"],
                                   "succeeded", result="changed", db_path=path,
                                   now=NOW)
            with open_queue_db(path) as connection:
                self.assertEqual(connection.execute(
                    "SELECT COUNT(*) FROM task_events WHERE action = 'succeeded'"
                ).fetchone()[0], 1)

    def test_strict_priority_beats_old_low_priority_task(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "queue.sqlite3"
            add_task(path, "old", priority=0,
                     ready_at=NOW - timedelta(hours=10))
            add_task(path, "new", priority=9)
            self.assertEqual(claim_next_task(path, NOW)["task"]["task_id"],
                             "new-instance")

    def test_failed_report_retries_and_lease_can_be_extended(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "queue.sqlite3"
            add_task(path, "retry")
            first = claim_next_task(path, NOW)["task"]
            extended = extend_task_lease(first["task_id"], first["lease_token"],
                                         path, NOW + timedelta(minutes=1))
            self.assertEqual(extended["lease_expires_at"],
                             stamp(NOW + timedelta(hours=1)))
            response = report_task_result(first["task_id"], first["lease_token"],
                                          "failed", error="temporary", db_path=path,
                                          now=NOW + timedelta(minutes=2))
            self.assertEqual(response["status"], "ready")
            self.assertIsNone(claim_next_task(path, NOW + timedelta(minutes=2))["task"])
            second = claim_next_task(path, NOW + timedelta(minutes=3))["task"]
            self.assertEqual(second["attempt"], 2)
            self.assertNotEqual(second["lease_token"], first["lease_token"])
            self.assertEqual(report_task_result(
                first["task_id"], first["lease_token"], "failed",
                error="temporary", db_path=path, now=NOW + timedelta(minutes=3)),
                response)
            with self.assertRaises(QueueConflict):
                extend_task_lease(first["task_id"], first["lease_token"],
                                  path, NOW + timedelta(minutes=3))

    def test_concurrent_claims_do_not_duplicate_a_task(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "queue.sqlite3"
            add_task(path, "only")
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: claim_next_task(path, NOW)["task"],
                                        range(2)))
            self.assertEqual(sum(task is not None for task in results), 1)

    def test_invalid_and_expired_reports_are_rejected(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "queue.sqlite3"
            add_task(path, "short")
            first = claim_next_task(path, NOW)["task"]
            with self.assertRaises(QueueConflict):
                report_task_result(first["task_id"], "wrong", "succeeded",
                                   result="done", db_path=path, now=NOW)
            with self.assertRaises(QueueConflict):
                report_task_result(first["task_id"], first["lease_token"],
                                   "succeeded", result="done", db_path=path,
                                   now=NOW + timedelta(minutes=31))
            with self.assertRaises(ValueError):
                report_task_result(first["task_id"], first["lease_token"],
                                   "succeeded", db_path=path, now=NOW)


if __name__ == "__main__":
    unittest.main()
