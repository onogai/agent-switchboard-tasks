"""Materialize scheduled work and reconcile overdue queue state."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
import sqlite3
from uuid import uuid4
from zoneinfo import ZoneInfo

from .db import open_queue_db, transaction
from .models import InstanceStatus, MissPolicy, ScheduleKind


MAX_OCCURRENCES_PER_REFRESH = 2000
FUTURE_HORIZON = timedelta(hours=24)


def utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Queue timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


def stamp(value: datetime) -> str:
    return utc(value).isoformat()


def parse(value: str) -> datetime:
    return utc(datetime.fromisoformat(value))


def retry_delay(attempt_count: int) -> timedelta:
    return timedelta(minutes=min(2 ** max(attempt_count - 1, 0), 60))


def window_for(definition: sqlite3.Row | dict, target: datetime) -> tuple[datetime, datetime]:
    return (target - timedelta(minutes=definition["window_before_minutes"]),
            target + timedelta(minutes=definition["max_lateness_minutes"]))


def event(connection: sqlite3.Connection, entity_type: str, entity_id: str,
          action: str, now: datetime, reason: str | None = None,
          actor: str = "scheduler") -> None:
    connection.execute(
        """INSERT INTO task_events
           (occurred_at, entity_type, entity_id, action, reason, actor)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (stamp(now), entity_type, entity_id, action, reason, actor),
    )


def _local_occurrence(day: date, local_time: str, zone: ZoneInfo) -> datetime | None:
    hour, minute = map(int, local_time.split(":"))
    naive = datetime.combine(day, time(hour, minute))
    candidate = naive.replace(tzinfo=zone, fold=0)
    # A nonexistent wall time does not survive a UTC round trip.
    if candidate.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) != naive:
        return None
    return utc(candidate)


def _adjacent_daily(current: datetime, local_time: str,
                    zone: ZoneInfo, direction: int) -> datetime:
    day = current.astimezone(zone).date()
    while True:
        day += timedelta(days=direction)
        candidate = _local_occurrence(day, local_time, zone)
        if candidate is not None:
            return candidate


def next_occurrence(definition: sqlite3.Row, current: datetime) -> datetime:
    if definition["schedule_kind"] == ScheduleKind.INTERVAL:
        return current + timedelta(minutes=definition["interval_minutes"])
    if definition["schedule_kind"] == ScheduleKind.DAILY:
        return _adjacent_daily(current, definition["daily_time_local"],
                               ZoneInfo(definition["timezone"]), 1)
    raise ValueError("Manual definitions have no next occurrence")


def previous_occurrence(definition: sqlite3.Row, current: datetime) -> datetime:
    if definition["schedule_kind"] == ScheduleKind.INTERVAL:
        return current - timedelta(minutes=definition["interval_minutes"])
    if definition["schedule_kind"] == ScheduleKind.DAILY:
        return _adjacent_daily(current, definition["daily_time_local"],
                               ZoneInfo(definition["timezone"]), -1)
    raise ValueError("Manual definitions have no previous occurrence")


def _merge_coverage(connection: sqlite3.Connection, row: sqlite3.Row,
                    source_start: str, now: datetime) -> bool:
    definition = connection.execute(
        "SELECT * FROM task_definitions WHERE id=?", (row["definition_id"],)
    ).fetchone()
    target = stamp(next_occurrence(definition, parse(row["scheduled_at"])))
    next_instance = connection.execute(
        """SELECT * FROM task_instances WHERE definition_id=? AND scheduled_at=?
           AND origin='scheduled' ORDER BY
           CASE WHEN status IN ('future','ready','leased') THEN 0 ELSE 1 END,
           created_at DESC LIMIT 1""", (row["definition_id"], target)
    ).fetchone()
    if next_instance is not None:
        if next_instance["status"] not in ("future", "ready") or next_instance["attempt_count"]:
            return False
        old_start = next_instance["coverage_start"]
        connection.execute(
            "UPDATE task_instances SET coverage_start=?, updated_at=? WHERE id=?",
            (min(source_start, old_start) if old_start else source_start,
             stamp(now), next_instance["id"]),
        )
        return True
    if (definition["next_scheduled_at"] is None
            or parse(definition["next_scheduled_at"]) > parse(target)):
        return False
    old_start = definition["pending_coverage_start"]
    connection.execute(
        "UPDATE task_definitions SET pending_coverage_start=?, updated_at=? WHERE id=?",
        (min(source_start, old_start) if old_start else source_start,
         stamp(now), row["definition_id"]),
    )
    return True


def _expire_leases(connection: sqlite3.Connection, now: datetime) -> None:
    rows = connection.execute(
        """SELECT i.*, d.is_active, d.archived_at FROM task_instances i
           JOIN task_definitions d ON d.id = i.definition_id
           WHERE i.status = 'leased' AND i.lease_expires_at < ?""",
        (stamp(now),),
    ).fetchall()
    for row in rows:
        connection.execute(
            """UPDATE task_attempts SET completed_at = ?, outcome = 'expired'
               WHERE lease_token = ? AND completed_at IS NULL""",
            (stamp(now), row["lease_token"]),
        )
        retry_at = now + retry_delay(row["attempt_count"])
        archived = row["archived_at"] is not None
        paused = not row["is_active"] or archived
        window_elapsed = (row["miss_policy_snapshot"] != MissPolicy.RUN_LATE
                          and row["window_end_at"] is not None
                          and retry_at > parse(row["window_end_at"]))
        if paused or window_elapsed or row["attempt_count"] >= row["max_attempts_snapshot"]:
            status = InstanceStatus.FAILED
            ready_at = row["ready_at"]
        else:
            status = InstanceStatus.READY
            ready_at = stamp(retry_at)
        reason = ("rule_archived" if archived else "rule_paused" if paused
                  else "retry_window_elapsed" if window_elapsed
                  else "Lease expired")
        connection.execute(
            """UPDATE task_instances SET status = ?, ready_at = ?,
               lease_token = NULL, lease_expires_at = NULL, updated_at = ?,
               last_error = ? WHERE id = ?""",
            (status, ready_at, stamp(now), reason, row["id"]),
        )
        event(connection, "instance", row["id"],
              "lease_expired" if status == InstanceStatus.READY else "failed",
              now, reason)


def _handle_overdue(connection: sqlite3.Connection, now: datetime) -> None:
    rows = connection.execute(
        """SELECT i.* FROM task_instances i JOIN task_definitions d ON d.id=i.definition_id
           WHERE i.status IN ('future', 'ready') AND d.is_active=1
             AND d.archived_at IS NULL
             AND (i.ready_at <= ? OR i.window_end_at < ?)
           ORDER BY i.definition_id, i.scheduled_at""",
        (stamp(now), stamp(now)),
    ).fetchall()
    for row in rows:
        # A previous merge in this pass may have expanded this row's coverage.
        coverage_start = connection.execute(
            "SELECT coverage_start FROM task_instances WHERE id = ?", (row["id"],)
        ).fetchone()[0]
        if row["status"] == InstanceStatus.FUTURE and parse(row["ready_at"]) <= now:
            connection.execute(
                "UPDATE task_instances SET status = 'ready', updated_at = ? WHERE id = ?",
                (stamp(now), row["id"]),
            )
            event(connection, "instance", row["id"], "ready", now)
        if row["miss_policy_snapshot"] == MissPolicy.RUN_LATE or row["window_end_at"] is None:
            continue
        if now <= parse(row["window_end_at"]):
            continue
        if row["attempt_count"]:
            status = InstanceStatus.FAILED
            reason = "retry_window_elapsed"
        elif row["miss_policy_snapshot"] == MissPolicy.MERGE_NEXT and coverage_start:
            transferred = _merge_coverage(connection, row, coverage_start, now)
            status = InstanceStatus.MERGED if transferred else InstanceStatus.SKIPPED
            reason = "window_elapsed" if transferred else "coalesce_target_unavailable"
        else:
            status = InstanceStatus.SKIPPED
            reason = "window_elapsed"
        connection.execute(
            "UPDATE task_instances SET status=?, last_error=?, updated_at=? WHERE id=?",
            (status, reason, stamp(now), row["id"]),
        )
        event(connection, "instance", row["id"], status, now, reason)


def _cap_run_late(connection: sqlite3.Connection, now: datetime) -> None:
    rows = connection.execute(
        """SELECT i.id, i.definition_id FROM task_instances i
           JOIN task_definitions d ON d.id=i.definition_id
           WHERE i.origin='scheduled' AND i.status IN ('future','ready')
             AND i.miss_policy_snapshot='run_late' AND i.window_end_at < ?
             AND d.is_active=1 AND d.archived_at IS NULL
           ORDER BY i.definition_id, i.scheduled_at DESC, i.id DESC""",
        (stamp(now),),
    ).fetchall()
    counts: dict[str, int] = {}
    for row in rows:
        count = counts.get(row["definition_id"], 0) + 1
        counts[row["definition_id"]] = count
        if count > 3:
            connection.execute(
                """UPDATE task_instances SET status='skipped', last_error='run_late_backlog_limit',
                   updated_at=? WHERE id=?""", (stamp(now), row["id"])
            )
            event(connection, "instance", row["id"], "skipped", now,
                  "run_late_backlog_limit")


def reconcile(connection: sqlite3.Connection, now: datetime) -> None:
    _expire_leases(connection, now)
    _handle_overdue(connection, now)
    _cap_run_late(connection, now)


def insert_scheduled(connection: sqlite3.Connection, definition: sqlite3.Row,
                     target: datetime, now: datetime, *, origin: str = "scheduled",
                     coverage_start: str | None = None) -> str | None:
    start, end = window_for(definition, target)
    # A target already materialized or handled must not run again merely because
    # the definition changed. Only scheduler-invalidated, unstarted cancellations
    # can be materialized again (e.g. after resuming or moving a schedule back).
    existing = connection.execute(
        """SELECT id FROM task_instances WHERE definition_id=? AND scheduled_at=?
           AND origin IN ('scheduled','one_shot')
           AND NOT (status='cancelled' AND attempt_count=0
                    AND COALESCE(last_error, '') IN ('rule_paused','schedule_changed'))
           LIMIT 1""",
        (definition["id"], stamp(target)),
    ).fetchone()
    if existing:
        return None
    identifier = uuid4().hex
    start_text = coverage_start
    connection.execute(
        """INSERT INTO task_instances
           (id, definition_id, definition_version, occurrence_key, title_snapshot,
            instructions_snapshot, priority_snapshot, scheduled_at, ready_at,
            window_start_at, window_end_at, origin, miss_policy_snapshot,
            lease_seconds_snapshot, max_attempts_snapshot, coverage_start, coverage_end,
            status, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (identifier, definition["id"], definition["version"],
         f'{definition["version"]}:{stamp(target)}', definition["title"],
         definition["instructions"], definition["priority"], stamp(target),
         stamp(start), stamp(start), stamp(end), origin, definition["miss_policy"],
         definition["lease_seconds"], definition["max_attempts"], start_text,
         stamp(target), "ready" if start <= now else "future", stamp(now), stamp(now)),
    )
    event(connection, "instance", identifier, "created", now)
    return identifier


def fill_schedule(connection: sqlite3.Connection, now: datetime,
                  definition_id: str | None = None) -> None:
    """Keep a rolling buffer of future instances for active schedules."""
    query = ("SELECT * FROM task_definitions WHERE is_active = 1 AND archived_at IS NULL "
             "AND schedule_kind != 'manual' AND next_scheduled_at IS NOT NULL")
    params: tuple[str, ...] = ()
    if definition_id is not None:
        query += " AND id = ?"
        params = (definition_id,)
    definitions = connection.execute(query, params).fetchall()
    for definition in definitions:
        next_at = parse(definition["next_scheduled_at"])
        pending_start = definition["pending_coverage_start"]
        count = 0
        horizon = now + FUTURE_HORIZON
        while window_for(definition, next_at)[0] <= horizon and count < MAX_OCCURRENCES_PER_REFRESH:
            coverage_start = pending_start or stamp(previous_occurrence(definition, next_at))
            instance_id = insert_scheduled(connection, definition, next_at, now,
                                           coverage_start=coverage_start)
            # An existing active target is a barrier: its coverage cannot change after claim.
            pending_start = None
            next_at = next_occurrence(definition, next_at)
            count += 1
        if count:
            connection.execute(
                """UPDATE task_definitions SET next_scheduled_at = ?,
                   pending_coverage_start = ?, updated_at = ? WHERE id = ?""",
                (stamp(next_at), pending_start, stamp(now), definition["id"]),
            )
        if count == MAX_OCCURRENCES_PER_REFRESH and window_for(definition, next_at)[0] <= horizon:
            event(connection, "definition", definition["id"], "generation_batch_limit",
                  now, f"Next ungenerated target: {stamp(next_at)}")


def refresh_queue(now: datetime | None = None, db_path: Path | None = None) -> None:
    """Reconcile due tasks and expired leases without generating new instances."""
    now = utc(now or datetime.now(timezone.utc))
    with open_queue_db(db_path) as connection:
        with transaction(connection):
            reconcile(connection, now)


def generate_future(now: datetime | None = None, db_path: Path | None = None) -> None:
    """Append missing instances through the next 24 hours, once per hourly tick."""
    now = utc(now or datetime.now(timezone.utc))
    with open_queue_db(db_path) as connection:
        with transaction(connection):
            fill_schedule(connection, now)
            reconcile(connection, now)
