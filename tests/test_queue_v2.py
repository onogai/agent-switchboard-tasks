"""Task Queue v2 invariants that did not exist in the first release."""
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import unittest

from task_queue.admin import (QueueAdminError, archive_definition, cancel_instance,
                              create_definition, get_definition, list_instances,
                              list_definitions,
                              refresh_pending_snapshots, retry_instance, trigger_definition,
                              update_definition)
from task_queue.db import SCHEMA_V1, open_queue_db, transaction
from task_queue.proposals import (auto_approval_state, decide_proposal, get_proposal,
                                  set_auto_approval, submit_proposal)
from task_queue.scheduler import generate_future, refresh_queue, stamp
from task_queue.service import claim_next_task, report_task_result

NOW = datetime(2026, 11, 3, 12, tzinfo=timezone.utc)


class QueueV2Tests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "queue.sqlite3"

    def rows(self, rule_id, now=NOW):
        return [row for row in list_instances(self.path, now=now)
                if row["definition_id"] == rule_id]

    def test_window_edit_recomputes_ready_at_and_future_ready_state(self):
        rule = create_definition("Window", "Old", schedule_kind="interval",
            interval_minutes=10, interval_anchor_at=stamp(NOW),
            db_path=self.path, now=NOW)
        future = next(row for row in self.rows(rule) if row["scheduled_at"] == stamp(NOW + timedelta(minutes=10)))
        update_definition(rule, {"window_before_minutes": 15, "instructions": "New"},
                          self.path, NOW + timedelta(minutes=1))
        opened = next(row for row in self.rows(rule, NOW + timedelta(minutes=1)) if row["id"] == future["id"])
        self.assertEqual(opened["status"], "ready")
        self.assertEqual(opened["ready_at"], stamp(NOW - timedelta(minutes=5)))
        self.assertEqual(opened["instructions_snapshot"], "New")
        self.assertEqual(max(row["scheduled_at"] for row in self.rows(rule, NOW + timedelta(minutes=1))
                             if row["status"] in ("future", "ready")),
                         stamp(NOW + timedelta(hours=24, minutes=10)))
        update_definition(rule, {"window_before_minutes": 0}, self.path,
                          NOW + timedelta(minutes=2))
        closed = next(row for row in self.rows(rule, NOW + timedelta(minutes=2)) if row["id"] == future["id"])
        self.assertEqual(closed["status"], "future")
        self.assertEqual(closed["ready_at"], stamp(NOW + timedelta(minutes=10)))

    def test_rule_edit_refreshes_all_unstarted_snapshots_and_preserves_history(self):
        rule = create_definition("Old", "v1", schedule_kind="interval",
            interval_minutes=10, interval_anchor_at=stamp(NOW),
            window_before_minutes=10, db_path=self.path, now=NOW - timedelta(minutes=10))
        finished = claim_next_task(self.path, NOW - timedelta(minutes=10))["task"]
        report_task_result(finished["task_id"], finished["lease_token"], "succeeded",
                           result="done", db_path=self.path, now=NOW - timedelta(minutes=10))
        leased = claim_next_task(self.path, NOW)["task"]
        manual = trigger_definition(rule, self.path, NOW)
        before = {row["id"]: row for row in self.rows(rule)}
        for version in (2, 3):
            update_definition(rule, {"title": "Current", "instructions": f"v{version}",
                "priority": 8, "miss_policy": "skip", "lease_seconds": 120,
                "max_attempts": 4, "max_lateness_minutes": 60},
                self.path, NOW)
        after = {row["id"]: row for row in self.rows(rule)}
        self.assertEqual(before.keys(), after.keys())
        for task in (finished, leased):
            self.assertEqual(after[task["task_id"]], before[task["task_id"]])
        for row in after.values():
            if row["status"] not in ("future", "ready"):
                continue
            self.assertEqual(row["definition_version"], 3)
            self.assertEqual(row["title_snapshot"], "Current")
            self.assertEqual(row["instructions_snapshot"], "v3")
            self.assertEqual(row["priority_snapshot"], 8)
            self.assertEqual(row["lease_seconds_snapshot"], 120)
            self.assertEqual(row["max_attempts_snapshot"], 4)
            if row["origin"] == "scheduled":
                self.assertEqual(row["occurrence_key"], "3:" + row["scheduled_at"])
                self.assertEqual(row["miss_policy_snapshot"], "skip")
                self.assertEqual(row["coverage_start"], before[row["id"]]["coverage_start"])
                self.assertEqual(row["window_end_at"], stamp(
                    datetime.fromisoformat(row["scheduled_at"]) + timedelta(minutes=60)))
        self.assertEqual(after[manual]["miss_policy_snapshot"], "run_late")
        self.assertIsNone(after[manual]["window_end_at"])
        claimed = claim_next_task(self.path, NOW)["task"]
        self.assertEqual(claimed["instructions"], "v3")
        self.assertEqual(claimed["priority"], 8)

    def test_schedule_edit_keeps_matching_ready_runs_without_repeating_completed_run(self):
        rule = create_definition("Interval", "Old", schedule_kind="interval",
            interval_minutes=10, interval_anchor_at=stamp(NOW),
            window_before_minutes=10, db_path=self.path, now=NOW - timedelta(minutes=10))
        task = claim_next_task(self.path, NOW - timedelta(minutes=10))["task"]
        report_task_result(task["task_id"], task["lease_token"], "succeeded",
                           result="done", db_path=self.path, now=NOW - timedelta(minutes=10))
        # The 12:00 target finished early. A new 20-minute grid still includes it.
        update_definition(rule, {"interval_minutes": 20, "instructions": "New"},
                          self.path, NOW - timedelta(minutes=5))
        generate_future(NOW, self.path)
        rows = self.rows(rule)
        self.assertEqual(len([row for row in rows if row["scheduled_at"] == stamp(NOW)]), 1)
        active = [row for row in rows if row["status"] in ("ready", "future")]
        self.assertEqual(len({row["scheduled_at"] for row in active}), len(active))
        self.assertTrue(all(row["definition_version"] == 2 for row in active))
        self.assertTrue(all(row["instructions_snapshot"] == "New" for row in active))
        self.assertTrue(all((datetime.fromisoformat(row["scheduled_at"]) - NOW)
                            % timedelta(minutes=20) == timedelta(0) for row in active))
        self.assertIn(stamp(NOW + timedelta(minutes=20)), {row["scheduled_at"] for row in active})

    def test_schedule_edit_preserves_matching_overdue_ready_target(self):
        rule = create_definition("Backlog", "Old", schedule_kind="interval",
            interval_minutes=10, interval_anchor_at=stamp(NOW), db_path=self.path, now=NOW)
        original = next(row for row in self.rows(rule) if row["scheduled_at"] == stamp(NOW))
        later = NOW + timedelta(minutes=21)
        update_definition(rule, {"interval_minutes": 20, "instructions": "New"},
                          self.path, later)
        row = next(row for row in self.rows(rule, later) if row["id"] == original["id"])
        self.assertEqual((row["status"], row["definition_version"], row["instructions_snapshot"]),
                         ("ready", 2, "New"))

    def test_one_shot_edit_updates_snapshot_and_reschedule_replaces_target(self):
        target = NOW + timedelta(minutes=30)
        rule = create_definition("Once", "Old", one_shot_at=stamp(target),
                                 db_path=self.path, now=NOW)
        original = self.rows(rule)[0]
        update_definition(rule, {"instructions": "New"}, self.path, NOW)
        row = self.rows(rule)[0]
        self.assertEqual((row["id"], row["definition_version"], row["instructions_snapshot"]),
                         (original["id"], 2, "New"))
        new_target = target + timedelta(minutes=10)
        update_definition(rule, {"one_shot_at": stamp(new_target)}, self.path, NOW)
        rows = self.rows(rule)
        self.assertEqual(next(row for row in rows if row["id"] == original["id"])["status"],
                         "cancelled")
        pending = [row for row in rows if row["status"] in ("future", "ready")]
        self.assertEqual(len(pending), 1)
        self.assertEqual((pending[0]["scheduled_at"], pending[0]["definition_version"]),
                         (stamp(new_target), 3))

    def test_reschedule_materializes_all_new_future_targets_in_early_window(self):
        rule = create_definition("Interval", "Old", schedule_kind="interval",
            interval_minutes=60, interval_anchor_at=stamp(NOW),
            window_before_minutes=30, db_path=self.path, now=NOW)
        later = NOW + timedelta(minutes=1)
        update_definition(rule, {"interval_minutes": 10}, self.path, later)
        active = [row for row in self.rows(rule, later)
                  if row["status"] in ("future", "ready")]
        for minutes in (10, 20, 30, 40):
            target = stamp(NOW + timedelta(minutes=minutes))
            self.assertEqual(sum(row["scheduled_at"] == target for row in active), 1)
        self.assertTrue(all(row["definition_version"] == 2 for row in active))

    def test_reschedule_preserves_coalesced_coverage_when_target_removed(self):
        rule = create_definition("Merge", "Work", schedule_kind="interval",
            interval_minutes=10, interval_anchor_at=stamp(NOW), miss_policy="merge_next",
            max_lateness_minutes=5, db_path=self.path, now=NOW)
        later = NOW + timedelta(minutes=6)
        refresh_queue(later, self.path)
        source = next(row for row in self.rows(rule, later)
                      if row["scheduled_at"] == stamp(NOW + timedelta(minutes=10)))
        self.assertEqual(source["coverage_start"], stamp(NOW - timedelta(minutes=10)))
        update_definition(rule, {"interval_minutes": 20}, self.path, later)
        rows = self.rows(rule, later)
        self.assertEqual(next(row for row in rows if row["id"] == source["id"])["status"],
                         "cancelled")
        next_run = next(row for row in rows
                        if row["scheduled_at"] == stamp(NOW + timedelta(minutes=20))
                        and row["status"] == "future")
        self.assertEqual(next_run["coverage_start"], source["coverage_start"])

    def test_startup_refresh_repairs_stale_pending_snapshots_idempotently(self):
        rule = create_definition("Original", "Old", schedule_kind="interval",
            interval_minutes=10, interval_anchor_at=stamp(NOW),
            db_path=self.path, now=NOW)
        leased = claim_next_task(self.path, NOW)["task"]
        manual = trigger_definition(rule, self.path, NOW)
        # Simulate the old database: rule changed without refreshing its instances.
        with open_queue_db(self.path) as db, transaction(db):
            db.execute("""UPDATE task_definitions SET version=9,title='Current',
                instructions='New',priority=8,lease_seconds=120,max_attempts=4,
                window_before_minutes=15 WHERE id=?""", (rule,))
        before = {row["id"]: row for row in self.rows(rule)}
        refresh_pending_snapshots(self.path, NOW)
        after = {row["id"]: row for row in self.rows(rule)}
        self.assertEqual(before.keys(), after.keys())
        self.assertEqual(after[leased["task_id"]], before[leased["task_id"]])
        self.assertEqual(after[manual]["instructions_snapshot"], "New")
        self.assertEqual(after[manual]["definition_version"], 9)
        for row in after.values():
            if row["status"] not in ("future", "ready"):
                continue
            self.assertEqual(row["definition_version"], 9)
            self.assertEqual(row["instructions_snapshot"], "New")
            self.assertEqual(row["lease_seconds_snapshot"], 120)
            if row["origin"] == "scheduled":
                self.assertEqual(row["occurrence_key"], "9:" + row["scheduled_at"])
                self.assertEqual(row["coverage_start"], before[row["id"]]["coverage_start"])
                self.assertEqual(row["ready_at"], stamp(
                    datetime.fromisoformat(row["scheduled_at"]) - timedelta(minutes=15)))
        refresh_pending_snapshots(self.path, NOW + timedelta(seconds=1))
        self.assertEqual(after, {row["id"]: row for row in self.rows(rule)})
        self.assertEqual(claim_next_task(self.path, NOW)["task"]["instructions"], "New")

    def test_window_claim_boundaries_are_inclusive(self):
        target = NOW + timedelta(minutes=30)
        rule = create_definition("Boundary", "Work", one_shot_at=stamp(target),
            window_before_minutes=10, max_lateness_minutes=5, miss_policy="skip",
            db_path=self.path, now=NOW)
        self.assertIsNone(claim_next_task(self.path, NOW + timedelta(minutes=19, seconds=59))["task"])
        claimed = claim_next_task(self.path, NOW + timedelta(minutes=20))["task"]
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed["scheduled_at"], stamp(target))

    def test_manual_retry_rejected_while_paused_or_archived(self):
        rule = create_definition("Manual", "Work", db_path=self.path, now=NOW)
        task = trigger_definition(rule, self.path, NOW)
        cancel_instance(task, self.path, NOW)
        update_definition(rule, {"is_active": False}, self.path, NOW)
        with self.assertRaises(QueueAdminError):
            retry_instance(task, self.path, NOW)
        with self.assertRaises(QueueAdminError):
            submit_proposal("retry_instance", {}, task, None, "agent", "paused-retry",
                            self.path, NOW)
        update_definition(rule, {"is_active": True}, self.path, NOW + timedelta(minutes=1))
        retry = retry_instance(task, self.path, NOW + timedelta(minutes=1))
        cancel_instance(retry, self.path, NOW + timedelta(minutes=1))
        archive_definition(rule, self.path, NOW + timedelta(minutes=2))
        with self.assertRaises(QueueAdminError):
            retry_instance(retry, self.path, NOW + timedelta(minutes=2))
        with self.assertRaises(QueueAdminError):
            submit_proposal("retry_instance", {}, retry, None, "agent", "archived-retry",
                            self.path, NOW + timedelta(minutes=2))

    def test_pending_coverage_survives_reopen(self):
        rule = create_definition("Merge", "Work", schedule_kind="interval",
            interval_minutes=10, interval_anchor_at=stamp(NOW),
            miss_policy="merge_next", max_lateness_minutes=5,
            db_path=self.path, now=NOW)
        with open_queue_db(self.path) as connection, transaction(connection):
            connection.execute("DELETE FROM task_instances WHERE definition_id=? AND scheduled_at>?",
                               (rule, stamp(NOW)))
            connection.execute("UPDATE task_definitions SET next_scheduled_at=? WHERE id=?",
                               (stamp(NOW + timedelta(minutes=10)), rule))
        refresh_queue(NOW + timedelta(minutes=6), self.path)
        self.assertEqual(get_definition(rule, self.path)["definition"]["pending_coverage_start"],
                         stamp(NOW - timedelta(minutes=10)))
        # New connection simulates a restart before the successor is generated.
        generate_future(NOW + timedelta(minutes=6), self.path)
        self.assertIsNone(get_definition(rule, self.path)["definition"]["pending_coverage_start"])
        successor = next(row for row in self.rows(rule, NOW + timedelta(minutes=6))
                         if row["scheduled_at"] == stamp(NOW + timedelta(minutes=10)))
        self.assertEqual(successor["coverage_start"], stamp(NOW - timedelta(minutes=10)))

    def test_retry_keeps_original_instructions_after_edit(self):
        rule = create_definition("Manual", "Original instructions", db_path=self.path, now=NOW)
        trigger_definition(rule, self.path, NOW)
        first = claim_next_task(self.path, NOW)["task"]
        report_task_result(first["task_id"], first["lease_token"], "failed",
                           error="temporary", db_path=self.path, now=NOW)
        update_definition(rule, {"instructions": "Updated instructions"}, self.path,
                          NOW + timedelta(seconds=1))
        second = claim_next_task(self.path, NOW + timedelta(minutes=1))["task"]
        self.assertEqual(second["task_id"], first["task_id"])
        self.assertEqual(second["instructions"], "Original instructions")

    def test_new_rule_with_overlapping_windows_creates_one_current_run(self):
        rule = create_definition("Overlap", "Work", schedule_kind="interval",
            interval_minutes=10, interval_anchor_at=stamp(NOW),
            window_before_minutes=30, db_path=self.path, now=NOW + timedelta(minutes=35))
        rows = self.rows(rule, NOW + timedelta(minutes=35))
        self.assertEqual(sum(row["status"] == "ready" for row in rows), 1)
        self.assertEqual(next(row["scheduled_at"] for row in rows if row["status"] == "ready"),
                         stamp(NOW + timedelta(minutes=60)))
        generate_future(NOW + timedelta(minutes=35), self.path)
        self.assertEqual(sum(row["status"] == "ready" for row in self.rows(rule, NOW + timedelta(minutes=35))), 1)

    def test_run_late_backlog_keeps_three_newest(self):
        start = NOW - timedelta(minutes=10)
        rule = create_definition("Backlog", "Work", schedule_kind="interval",
            interval_minutes=1, interval_anchor_at=stamp(start), max_lateness_minutes=0,
            db_path=self.path, now=start)
        refresh_queue(NOW, self.path)
        overdue = [row for row in self.rows(rule, NOW) if row["scheduled_at"] < stamp(NOW)]
        self.assertEqual(sum(row["status"] == "ready" for row in overdue), 3)
        self.assertEqual({row["scheduled_at"] for row in overdue if row["status"] == "ready"},
                         {stamp(NOW - timedelta(minutes=n)) for n in (1, 2, 3)})
        self.assertTrue(all(row["last_error"] == "run_late_backlog_limit"
                            for row in overdue if row["status"] == "skipped"))

    def test_pause_discards_scheduled_periods_and_resume_starts_current_schedule(self):
        rule = create_definition("Pause", "Work", schedule_kind="interval",
            interval_minutes=10, interval_anchor_at=stamp(NOW),
            miss_policy="run_late", db_path=self.path, now=NOW)
        update_definition(rule, {"is_active": False}, self.path, NOW + timedelta(minutes=1))
        self.assertTrue(all(row["status"] == "cancelled" for row in self.rows(rule)))
        update_definition(rule, {"is_active": True}, self.path, NOW + timedelta(minutes=65))
        active = [row for row in self.rows(rule, NOW + timedelta(minutes=65))
                  if row["status"] in ("future", "ready", "leased")]
        self.assertEqual(min(row["scheduled_at"] for row in active),
                         stamp(NOW + timedelta(minutes=70)))
        self.assertIsNone(get_definition(rule, self.path)["definition"]["pending_coverage_start"])

    def test_one_shot_never_recreated_after_claim_and_resume(self):
        target = NOW + timedelta(minutes=10)
        rule = create_definition("Once", "Work", schedule_kind="manual",
            one_shot_at=stamp(target), window_before_minutes=20,
            db_path=self.path, now=NOW)
        task = claim_next_task(self.path, NOW)["task"]
        self.assertIsNotNone(task)
        update_definition(rule, {"is_active": False}, self.path, NOW + timedelta(minutes=1))
        update_definition(rule, {"is_active": True}, self.path, NOW + timedelta(minutes=2))
        self.assertEqual(len([row for row in self.rows(rule, NOW + timedelta(minutes=2))
                              if row["origin"] == "one_shot"]), 1)

    def test_coalesce_does_not_cross_a_claimed_next_target(self):
        rule = create_definition("Merge", "Work", schedule_kind="interval",
            interval_minutes=10, interval_anchor_at=stamp(NOW),
            miss_policy="merge_next", max_lateness_minutes=5,
            db_path=self.path, now=NOW)
        source = next(row for row in self.rows(rule) if row["scheduled_at"] == stamp(NOW))
        target = next(row for row in self.rows(rule) if row["scheduled_at"] == stamp(NOW + timedelta(minutes=10)))
        with open_queue_db(self.path) as connection, transaction(connection):
            connection.execute("""UPDATE task_instances SET status='leased',attempt_count=1,
               lease_token='claimed-next',lease_expires_at=? WHERE id=?""",
               (stamp(NOW + timedelta(minutes=20)), target["id"]))
            connection.execute("""INSERT INTO task_attempts
               (instance_id,attempt_number,lease_token,claimed_at)
               VALUES (?,1,'claimed-next',?)""", (target["id"], stamp(NOW + timedelta(minutes=10))))
        refresh_queue(NOW + timedelta(minutes=11), self.path)
        source_after = next(row for row in self.rows(rule, NOW + timedelta(minutes=11))
                            if row["id"] == source["id"])
        self.assertEqual((source_after["status"], source_after["last_error"]),
                         ("skipped", "coalesce_target_unavailable"))
        self.assertEqual(next(row for row in self.rows(rule, NOW + timedelta(minutes=11))
                              if row["id"] == target["id"])["coverage_start"], stamp(NOW))

    def test_lease_and_attempt_limits_are_snapshotted(self):
        rule = create_definition("Snapshots", "Work", lease_seconds=60,
                                 max_attempts=2, db_path=self.path, now=NOW)
        trigger_definition(rule, self.path, NOW)
        first = claim_next_task(self.path, NOW)["task"]
        update_definition(rule, {"lease_seconds": 3600, "max_attempts": 1},
                          self.path, NOW + timedelta(seconds=1))
        from task_queue.service import extend_task_lease
        extended = extend_task_lease(first["task_id"], first["lease_token"],
                                     self.path, NOW + timedelta(seconds=30))
        self.assertEqual(extended["lease_expires_at"], stamp(NOW + timedelta(seconds=120)))
        result = report_task_result(first["task_id"], first["lease_token"], "failed",
                                    error="temporary", db_path=self.path,
                                    now=NOW + timedelta(seconds=40))
        self.assertEqual(result["status"], "ready")

    def test_proposal_pending_idempotent_then_approved(self):
        rule = {"title": "Proposed", "instructions": "Run"}
        first = submit_proposal("create_rule", rule, None, None, "agent", "key-1",
                                self.path, NOW)
        self.assertEqual(first["status"], "pending")
        self.assertEqual(list_instances(self.path, now=NOW), [])
        same = submit_proposal("create_rule", rule, None, None, "agent", "key-1",
                               self.path, NOW)
        self.assertEqual(same["id"], first["id"])
        approved = decide_proposal(first["id"], True, "pin-session", self.path, NOW)
        self.assertEqual(approved["status"], "approved")
        self.assertEqual(decide_proposal(first["id"], True, "pin-session", self.path, NOW)["result"],
                         approved["result"])
        self.assertEqual(len([r for r in self.rows(approved["result"]["id"]) if r["status"] == "ready"]), 0)

    def test_auto_approval_only_new_proposals_and_expires(self):
        old = submit_proposal("create_rule", {"title": "Old", "instructions": "Run"},
                              None, None, "agent", "old", self.path, NOW)
        enabled = set_auto_approval(True, "pin-session", self.path, NOW)
        self.assertEqual(set_auto_approval(True, "pin-session", self.path,
                                           NOW + timedelta(minutes=30))["until"],
                         enabled["until"])
        new = submit_proposal("create_rule", {"title": "New", "instructions": "Run"},
                              None, None, "agent", "new", self.path, NOW)
        self.assertEqual(new["status"], "approved")
        self.assertEqual(get_proposal(old["id"], self.path)["status"], "pending")
        self.assertEqual(submit_proposal("create_rule", {"title": "Old", "instructions": "Run"},
                                         None, None, "agent", "old", self.path, NOW)["status"],
                         "pending")
        self.assertFalse(auto_approval_state(self.path, NOW + timedelta(hours=1))["enabled"])
        later = submit_proposal("create_rule", {"title": "Later", "instructions": "Run"},
                                None, None, "agent", "later", self.path,
                                NOW + timedelta(hours=1))
        self.assertEqual(later["status"], "pending")

    def test_stale_proposals_do_not_apply(self):
        rule = create_definition("Version", "Old", db_path=self.path, now=NOW)
        proposal = submit_proposal("update_rule", {"instructions": "Proposed"}, rule, 1,
                                   "agent", "stale", self.path, NOW)
        update_definition(rule, {"instructions": "Newer"}, self.path, NOW)
        decision = decide_proposal(proposal["id"], True, "pin-session", self.path, NOW)
        self.assertEqual(decision["status"], "stale")
        self.assertEqual(get_definition(rule, self.path)["definition"]["instructions"], "Newer")
        target = NOW + timedelta(minutes=5)
        too_late = submit_proposal("create_rule", {"title": "Expired", "instructions": "Run",
            "schedule_kind": "one_shot", "one_shot_at": stamp(target),
            "window_after_minutes": 0}, None, None, "agent", "expired", self.path, NOW)
        decision = decide_proposal(too_late["id"], True, "pin-session", self.path,
                                   target + timedelta(seconds=1))
        self.assertEqual(decision["status"], "stale")
        self.assertNotIn("Expired", [row["title"] for row in list_definitions(self.path)])

    def test_concurrent_decisions_apply_once(self):
        proposal = submit_proposal("create_rule", {"title": "Single", "instructions": "Run"},
                                   None, None, "agent", "single", self.path, NOW)
        with ThreadPoolExecutor(max_workers=2) as pool:
            decisions = list(pool.map(lambda _: decide_proposal(
                proposal["id"], True, "pin-session", self.path, NOW), range(2)))
        self.assertEqual({row["status"] for row in decisions}, {"approved"})
        self.assertEqual(len([row for row in list_definitions(self.path)
                              if row["title"] == "Single"]), 1)

    def test_v1_migration_preserves_history_and_is_repeatable(self):
        connection = sqlite3.connect(self.path, isolation_level=None)
        try:
            for statement in SCHEMA_V1:
                connection.execute(statement)
            connection.execute("PRAGMA user_version=1")
            connection.execute("""INSERT INTO task_definitions
                (id,title,instructions,schedule_kind,created_at,updated_at)
                VALUES ('old','Old','Run','manual',?,?)""", (stamp(NOW), stamp(NOW)))
            connection.execute("""INSERT INTO task_instances
                (id,definition_id,definition_version,occurrence_key,title_snapshot,
                 instructions_snapshot,priority_snapshot,scheduled_at,ready_at,status,
                 created_at,updated_at)
                VALUES ('done','old',1,'manual:done','Old','Run',5,?,?,'succeeded',?,?)""",
                (stamp(NOW), stamp(NOW), stamp(NOW), stamp(NOW)))
        finally:
            connection.close()
        with open_queue_db(self.path) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT status FROM task_instances WHERE id='done'").fetchone()[0],
                             "succeeded")
        with open_queue_db(self.path) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM task_instances").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
