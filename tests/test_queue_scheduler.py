"""Tests for schedule materialization and missed-run policies."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from task_queue.db import open_queue_db, transaction
from task_queue.scheduler import generate_future, next_occurrence, refresh_queue, stamp


START = datetime(2026, 11, 3, 12, tzinfo=timezone.utc)


def definition(path: Path, *, policy: str = "run_late", lateness: int = 5,
               next_at: datetime = START) -> None:
    with open_queue_db(path) as connection:
        with transaction(connection):
            connection.execute(
                """INSERT INTO task_definitions
                   (id, title, instructions, schedule_kind, interval_minutes,
                    interval_anchor_at, miss_policy, max_lateness_minutes,
                    next_scheduled_at, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                ("hourly", "Market review", "Review the market.", "interval", 10,
                 stamp(START), policy, lateness, stamp(next_at), stamp(START),
                 stamp(START)),
            )


def instances(path: Path):
    with open_queue_db(path) as connection:
        return connection.execute(
            """SELECT scheduled_at, coverage_start, coverage_end, status, ready_at
               FROM task_instances ORDER BY scheduled_at"""
        ).fetchall()


def due_instances(path: Path, now: datetime):
    return [row for row in instances(path) if row["scheduled_at"] <= stamp(now)]


class QueueSchedulerTests(unittest.TestCase):
    def test_interval_generation_is_repeatable_without_duplicates(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "queue.sqlite3"
            definition(path)
            generate_future(START, path)
            generate_future(START, path)
            self.assertEqual(len(due_instances(path, START)), 1)
            refresh_queue(START + timedelta(minutes=20), path)
            rows = due_instances(path, START + timedelta(minutes=20))
            self.assertEqual([row["status"] for row in rows], ["ready"] * 3)
            self.assertEqual(rows[0]["coverage_start"],
                             stamp(START - timedelta(minutes=10)))
            self.assertEqual(rows[2]["coverage_end"],
                             stamp(START + timedelta(minutes=20)))

    def test_merge_next_accumulates_all_missed_windows(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "queue.sqlite3"
            definition(path, policy="merge_next")
            generate_future(START - timedelta(minutes=1), path)
            refresh_queue(START + timedelta(minutes=21), path)
            rows = due_instances(path, START + timedelta(minutes=21))
            self.assertEqual([row["status"] for row in rows],
                             ["merged", "merged", "ready"])
            self.assertEqual(rows[2]["coverage_start"],
                             stamp(START - timedelta(minutes=10)))
            refresh_queue(START + timedelta(minutes=26), path)
            rows = due_instances(path, START + timedelta(minutes=26))
            self.assertEqual(rows[2]["status"], "merged")
            with open_queue_db(path) as connection:
                self.assertEqual(connection.execute(
                    """SELECT coverage_start FROM task_instances
                       WHERE scheduled_at = ?""",
                    (stamp(START + timedelta(minutes=30)),),
                ).fetchone()[0], stamp(START - timedelta(minutes=10)))
            refresh_queue(START + timedelta(minutes=30), path)
            self.assertEqual(due_instances(path, START + timedelta(minutes=30))[3]["coverage_start"],
                             stamp(START - timedelta(minutes=10)))

    def test_skip_boundary_is_inclusive(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "queue.sqlite3"
            definition(path, policy="skip")
            generate_future(START - timedelta(minutes=1), path)
            refresh_queue(START + timedelta(minutes=5), path)
            self.assertEqual(due_instances(path, START)[0]["status"], "ready")
            refresh_queue(START + timedelta(minutes=5, microseconds=1), path)
            self.assertEqual(due_instances(path, START)[0]["status"], "skipped")

    def test_expired_lease_requeues_then_fails_after_limit(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "queue.sqlite3"
            definition(path)
            generate_future(START, path)
            with open_queue_db(path) as connection:
                with transaction(connection):
                    instance_id = connection.execute(
                        "SELECT id FROM task_instances WHERE scheduled_at = ?",
                        (stamp(START),),
                    ).fetchone()[0]
                    connection.execute(
                        """UPDATE task_instances SET status = 'leased', attempt_count = 1,
                           lease_token = 'token-1', lease_expires_at = ? WHERE id = ?""",
                        (stamp(START + timedelta(minutes=1)), instance_id),
                    )
                    connection.execute(
                        """INSERT INTO task_attempts
                           (instance_id, attempt_number, lease_token, claimed_at)
                           VALUES (?, 1, 'token-1', ?)""",
                        (instance_id, stamp(START)),
                    )
            refresh_queue(START + timedelta(minutes=2), path)
            row = due_instances(path, START)[0]
            self.assertEqual(row["status"], "ready")
            self.assertEqual(row["ready_at"], stamp(START + timedelta(minutes=3)))
            with open_queue_db(path) as connection:
                self.assertEqual(connection.execute(
                    "SELECT outcome FROM task_attempts"
                ).fetchone()[0], "expired")

    def test_daily_schedule_skips_spring_gap_and_uses_first_fall_hour(self):
        definition_row = {
            "schedule_kind": "daily",
            "daily_time_local": "02:30",
            "timezone": "Europe/Madrid",
        }
        spring = datetime(2026, 3, 28, 1, 30, tzinfo=timezone.utc)
        self.assertEqual(next_occurrence(definition_row, spring),
                         datetime(2026, 3, 30, 0, 30, tzinfo=timezone.utc))
        fall = datetime(2026, 10, 24, 0, 30, tzinfo=timezone.utc)
        self.assertEqual(next_occurrence(definition_row, fall),
                         datetime(2026, 10, 25, 0, 30, tzinfo=timezone.utc))


if __name__ == "__main__":
    unittest.main()
