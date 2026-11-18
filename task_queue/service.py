"""Agent-facing operations on the durable task queue."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import secrets
import sqlite3

from .db import open_queue_db, transaction
from .models import InstanceStatus
from .scheduler import event, parse, reconcile, retry_delay, stamp, utc


class QueueConflict(ValueError):
    """The task state or lease no longer permits the requested action."""


def _eligible_instances(connection: sqlite3.Connection, now: datetime) -> sqlite3.Row | None:
    return connection.execute(
        """SELECT i.*
           FROM task_instances i JOIN task_definitions d ON d.id = i.definition_id
           WHERE i.status = 'ready' AND i.ready_at <= ? AND d.is_active = 1
             AND d.archived_at IS NULL
             AND i.attempt_count < i.max_attempts_snapshot
             AND (i.miss_policy_snapshot='run_late' OR i.window_end_at >= ?)
           ORDER BY i.priority_snapshot DESC, i.ready_at ASC, i.id ASC LIMIT 1""",
        (stamp(now), stamp(now)),
    ).fetchone()


def claim_next_task(db_path: Path | None = None,
                    now: datetime | None = None) -> dict:
    """Atomically lease the highest-priority ready task, if any."""
    now = utc(now or datetime.now(timezone.utc))
    with open_queue_db(db_path) as connection:
        with transaction(connection):
            reconcile(connection, now)
            row = _eligible_instances(connection, now)
            if row is None:
                return {"task": None}
            token = secrets.token_urlsafe(32)
            attempt = row["attempt_count"] + 1
            expires_at = stamp(now + timedelta(seconds=row["lease_seconds_snapshot"]))
            connection.execute(
                """UPDATE task_instances SET status = 'leased', attempt_count = ?,
                   lease_token = ?, lease_expires_at = ?, updated_at = ? WHERE id = ?""",
                (attempt, token, expires_at, stamp(now), row["id"]),
            )
            connection.execute(
                """INSERT INTO task_attempts
                   (instance_id, attempt_number, lease_token, claimed_at)
                   VALUES (?, ?, ?, ?)""",
                (row["id"], attempt, token, stamp(now)),
            )
            event(connection, "instance", row["id"], "claimed", now, actor="agent")
            return {"task": {
                "task_id": row["id"],
                "definition_id": row["definition_id"],
                "title": row["title_snapshot"],
                "instructions": row["instructions_snapshot"],
                "scheduled_at": row["scheduled_at"],
                "coverage_start": row["coverage_start"],
                "coverage_end": row["coverage_end"],
                "priority": row["priority_snapshot"],
                "attempt": attempt,
                "lease_expires_at": expires_at,
                "lease_token": token,
            }}


def _active_lease(connection: sqlite3.Connection, task_id: str,
                  lease_token: str, now: datetime) -> sqlite3.Row:
    row = connection.execute(
        "SELECT * FROM task_instances WHERE id = ?", (task_id,)
    ).fetchone()
    if (row is None or row["status"] != InstanceStatus.LEASED
            or row["lease_token"] != lease_token
            or parse(row["lease_expires_at"]) < now):
        raise QueueConflict("Task lease is missing, expired, or owned by another agent.")
    return row


def extend_task_lease(task_id: str, lease_token: str,
                      db_path: Path | None = None,
                      now: datetime | None = None) -> dict:
    """Extend a valid lease by the definition's configured duration."""
    now = utc(now or datetime.now(timezone.utc))
    with open_queue_db(db_path) as connection:
        with transaction(connection):
            row = _active_lease(connection, task_id, lease_token, now)
            new_expiry = stamp(max(now, parse(row["lease_expires_at"]))
                               + timedelta(seconds=row["lease_seconds_snapshot"]))
            connection.execute(
                """UPDATE task_instances SET lease_expires_at = ?, updated_at = ?
                   WHERE id = ?""",
                (new_expiry, stamp(now), task_id),
            )
            event(connection, "instance", task_id, "lease_extended", now, actor="agent")
            return {"task_id": task_id, "lease_expires_at": new_expiry}


def report_task_result(task_id: str, lease_token: str, status: str,
                       result: str | None = None, error: str | None = None,
                       db_path: Path | None = None,
                       now: datetime | None = None) -> dict:
    """Record one final report for a lease; identical retries are idempotent."""
    if status == InstanceStatus.SUCCEEDED:
        if not result or error is not None:
            raise ValueError("A successful report needs a result and no error.")
    elif status == InstanceStatus.FAILED:
        if not error or result is not None:
            raise ValueError("A failed report needs an error and no result.")
    else:
        raise ValueError("status must be 'succeeded' or 'failed'.")

    now = utc(now or datetime.now(timezone.utc))
    payload = json.dumps({"status": status, "result": result, "error": error},
                         sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    report_hash = sha256(payload.encode("utf-8")).hexdigest()
    with open_queue_db(db_path) as connection:
        with transaction(connection):
            attempt = connection.execute(
                """SELECT * FROM task_attempts
                   WHERE instance_id = ? AND lease_token = ?""",
                (task_id, lease_token),
            ).fetchone()
            if attempt is None:
                raise QueueConflict("Unknown task lease.")
            if attempt["report_hash"] is not None:
                if attempt["report_hash"] != report_hash:
                    raise QueueConflict("This lease already has a different report.")
                return json.loads(attempt["report_response_json"])

            row = _active_lease(connection, task_id, lease_token, now)
            if status == InstanceStatus.SUCCEEDED:
                next_status = InstanceStatus.SUCCEEDED
                ready_at = row["ready_at"]
            else:
                definition = connection.execute(
                    "SELECT is_active, archived_at FROM task_definitions WHERE id=?",
                    (row["definition_id"],),
                ).fetchone()
                retry_at = now + retry_delay(row["attempt_count"])
                archived = definition["archived_at"] is not None
                paused = not definition["is_active"] or archived
                window_elapsed = (row["miss_policy_snapshot"] != "run_late"
                                  and row["window_end_at"] is not None
                                  and retry_at > parse(row["window_end_at"]))
                if (paused or window_elapsed
                        or row["attempt_count"] >= row["max_attempts_snapshot"]):
                    next_status = InstanceStatus.FAILED
                    ready_at = row["ready_at"]
                else:
                    next_status = InstanceStatus.READY
                    ready_at = stamp(retry_at)

            response = {"task_id": task_id, "status": next_status}
            if next_status == InstanceStatus.READY:
                response["next_available_at"] = ready_at
            final_error = ("rule_archived" if status == InstanceStatus.FAILED and archived
                           else "rule_paused" if status == InstanceStatus.FAILED and paused
                           else "retry_window_elapsed" if status == InstanceStatus.FAILED and window_elapsed
                           else error)
            connection.execute(
                """UPDATE task_instances SET status = ?, ready_at = ?,
                   lease_token = NULL, lease_expires_at = NULL, result_json = ?,
                   last_error = ?, updated_at = ? WHERE id = ?""",
                (next_status, ready_at,
                 json.dumps(result, ensure_ascii=False) if result is not None else None,
                 final_error, stamp(now), task_id),
            )
            connection.execute(
                """UPDATE task_attempts SET completed_at = ?, outcome = ?,
                   result_json = ?, error = ?, report_hash = ?, report_response_json = ?
                   WHERE id = ?""",
                (stamp(now), status,
                 json.dumps(result, ensure_ascii=False) if result is not None else None,
                 error, report_hash, json.dumps(response), attempt["id"]),
            )
            event(connection, "instance", task_id, status, now, final_error, actor="agent")
            return response
