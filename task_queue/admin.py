"""Queue administration shared by PIN UI and proposal decisions."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import floor
from pathlib import Path
import sqlite3
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .db import open_queue_db, transaction
from .models import InstanceStatus, MissPolicy, ScheduleKind
from .scheduler import (_local_occurrence, event, fill_schedule, insert_scheduled,
                        next_occurrence, parse, previous_occurrence, reconcile,
                        refresh_queue, stamp, utc, window_for)


class QueueAdminError(ValueError):
    """Invalid or stale administrative operation."""


def _timestamp(value: str | None, name: str) -> str | None:
    if value is None or value == "":
        return None
    try:
        return stamp(parse(value))
    except (ValueError, TypeError) as exc:
        raise QueueAdminError(f"{name} must be a timezone-aware ISO timestamp.") from exc


def _settings(title: str, instructions: str, schedule_kind: str,
              priority: int, miss_policy: str, max_lateness_minutes: int,
              lease_seconds: int, max_attempts: int,
              interval_minutes: int | None, interval_anchor_at: str | None,
              daily_time_local: str | None, timezone_name: str | None,
              now: datetime, window_before_minutes: int = 0,
              one_shot_at: str | None = None) -> dict:
    title, instructions = title.strip(), instructions.strip()
    if not title or len(title) > 200:
        raise QueueAdminError("Title must contain 1–200 characters.")
    if not instructions or len(instructions) > 100_000:
        raise QueueAdminError("Instructions must contain 1–100,000 characters.")
    if schedule_kind not in {kind.value for kind in ScheduleKind}:
        raise QueueAdminError("Unknown schedule kind.")
    if type(priority) is not int or not 0 <= priority <= 9:
        raise QueueAdminError("Priority must be an integer from 0 to 9.")
    if miss_policy not in {policy.value for policy in MissPolicy}:
        raise QueueAdminError("Unknown missed-run policy.")
    if (type(max_lateness_minutes) is not int or max_lateness_minutes < 0
            or type(window_before_minutes) is not int or window_before_minutes < 0):
        raise QueueAdminError("Window minutes must be nonnegative integers.")
    if type(lease_seconds) is not int or lease_seconds <= 0:
        raise QueueAdminError("lease_seconds must be positive.")
    if type(max_attempts) is not int or max_attempts <= 0:
        raise QueueAdminError("max_attempts must be positive.")
    one_shot_at = _timestamp(one_shot_at, "one_shot_at")
    interval_anchor_at = _timestamp(interval_anchor_at, "interval_anchor_at")
    if schedule_kind == ScheduleKind.MANUAL:
        if any(x is not None for x in (interval_minutes, interval_anchor_at,
                                       daily_time_local, timezone_name)):
            raise QueueAdminError("Manual and one-shot rules cannot have recurring timing settings.")
        if miss_policy == MissPolicy.MERGE_NEXT:
            raise QueueAdminError("Manual and one-shot rules cannot merge into a next run.")
        if one_shot_at is None and miss_policy != MissPolicy.RUN_LATE:
            raise QueueAdminError("Manual-only rules use run_late.")
    elif schedule_kind == ScheduleKind.INTERVAL:
        if one_shot_at is not None or daily_time_local is not None or timezone_name is not None:
            raise QueueAdminError("Interval rules cannot have one-shot or daily settings.")
        if type(interval_minutes) is not int or interval_minutes <= 0:
            raise QueueAdminError("Interval schedules need a positive number of minutes.")
        if (1440 + window_before_minutes) // interval_minutes + 2 > 2000:
            raise QueueAdminError("Interval and early window exceed generation limit.")
        interval_anchor_at = interval_anchor_at or stamp(now)
    else:
        if any(x is not None for x in (one_shot_at, interval_minutes, interval_anchor_at)):
            raise QueueAdminError("Daily rules cannot have interval or one-shot settings.")
        try:
            hour, minute = map(int, (daily_time_local or "").split(":"))
            if not 0 <= hour <= 23 or not 0 <= minute <= 59:
                raise ValueError
            daily_time_local = f"{hour:02d}:{minute:02d}"
            ZoneInfo(timezone_name or "")
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise QueueAdminError("Daily schedules need HH:MM and a valid IANA timezone.") from exc
    return dict(title=title, instructions=instructions, schedule_kind=schedule_kind,
                priority=priority, miss_policy=miss_policy,
                max_lateness_minutes=max_lateness_minutes,
                window_before_minutes=window_before_minutes,
                lease_seconds=lease_seconds, max_attempts=max_attempts,
                interval_minutes=interval_minutes, interval_anchor_at=interval_anchor_at,
                daily_time_local=daily_time_local, timezone=timezone_name,
                one_shot_at=one_shot_at)


def _occurrence(rule: sqlite3.Row, at: datetime, *, previous: bool = False,
                inclusive: bool = True) -> datetime:
    if rule["schedule_kind"] == ScheduleKind.INTERVAL:
        anchor = parse(rule["interval_anchor_at"])
        period = timedelta(minutes=rule["interval_minutes"])
        step = floor((at - anchor) / period)
        candidate = anchor + step * period
        if previous:
            return candidate
        return candidate if inclusive and candidate == at else candidate + period
    zone = ZoneInfo(rule["timezone"])
    day = at.astimezone(zone).date()
    for offset in range(370):
        date = day - timedelta(days=offset) if previous else day + timedelta(days=offset)
        candidate = _local_occurrence(date, rule["daily_time_local"], zone)
        if candidate is not None and (candidate <= at if previous else
                                      candidate > at or inclusive and candidate == at):
            return candidate
    raise QueueAdminError("Cannot find a daily occurrence.")


def _initialize_schedule(connection: sqlite3.Connection, rule_id: str,
                         now: datetime, *, resume: bool = False) -> None:
    rule = connection.execute("SELECT * FROM task_definitions WHERE id=?", (rule_id,)).fetchone()
    if rule["schedule_kind"] == ScheduleKind.MANUAL:
        if rule["one_shot_at"] and rule["is_active"]:
            target = parse(rule["one_shot_at"])
            _start, end = window_for(rule, target)
            started = connection.execute(
                """SELECT 1 FROM task_instances WHERE definition_id=? AND origin='one_shot'
                   AND attempt_count>0 LIMIT 1""", (rule_id,),
            ).fetchone()
            if not started and now <= end and (not resume or target >= now):
                insert_scheduled(connection, rule, target, now, origin="one_shot")
        return
    if resume:
        next_at = _occurrence(rule, now)
    else:
        cutoff = now + timedelta(minutes=rule["window_before_minutes"])
        latest = _occurrence(rule, cutoff, previous=True)
        if (rule["schedule_kind"] != ScheduleKind.INTERVAL
                or latest >= parse(rule["interval_anchor_at"])):
            if now <= window_for(rule, latest)[1]:
                insert_scheduled(connection, rule, latest, now,
                                 coverage_start=stamp(previous_occurrence(rule, latest)))
        next_at = next_occurrence(rule, latest)
        if rule["schedule_kind"] == ScheduleKind.INTERVAL:
            next_at = max(next_at, parse(rule["interval_anchor_at"]))
    connection.execute("UPDATE task_definitions SET next_scheduled_at=? WHERE id=?",
                       (stamp(next_at), rule_id))
    fill_schedule(connection, now, rule_id)
    reconcile(connection, now)


def apply_create(connection: sqlite3.Connection, payload: dict, now: datetime) -> str:
    data = _settings(now=now, **payload)
    if (data["one_shot_at"] is not None
            and now > parse(data["one_shot_at"]) + timedelta(
                minutes=data["max_lateness_minutes"])):
        raise QueueAdminError("One-shot window has already closed.")
    rule_id = uuid4().hex
    connection.execute(
        """INSERT INTO task_definitions
           (id,title,instructions,priority,schedule_kind,interval_minutes,
            interval_anchor_at,daily_time_local,timezone,miss_policy,
            max_lateness_minutes,window_before_minutes,lease_seconds,max_attempts,
            one_shot_at,created_at,updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (rule_id, data["title"], data["instructions"], data["priority"],
         data["schedule_kind"], data["interval_minutes"], data["interval_anchor_at"],
         data["daily_time_local"], data["timezone"], data["miss_policy"],
         data["max_lateness_minutes"], data["window_before_minutes"],
         data["lease_seconds"], data["max_attempts"], data["one_shot_at"],
         stamp(now), stamp(now)),
    )
    event(connection, "definition", rule_id, "created", now, actor="admin")
    _initialize_schedule(connection, rule_id, now)
    return rule_id


def create_definition(title: str, instructions: str, schedule_kind: str = "manual",
                      priority: int = 5, miss_policy: str = "run_late",
                      max_lateness_minutes: int = 30, lease_seconds: int = 1800,
                      max_attempts: int = 3, interval_minutes: int | None = None,
                      interval_anchor_at: str | None = None,
                      daily_time_local: str | None = None,
                      timezone_name: str | None = None,
                      db_path: Path | None = None, now: datetime | None = None,
                      window_before_minutes: int = 0,
                      one_shot_at: str | None = None) -> str:
    now = utc(now or datetime.now(timezone.utc))
    payload = dict(title=title, instructions=instructions, schedule_kind=schedule_kind,
                   priority=priority, miss_policy=miss_policy,
                   max_lateness_minutes=max_lateness_minutes, lease_seconds=lease_seconds,
                   max_attempts=max_attempts, interval_minutes=interval_minutes,
                   interval_anchor_at=interval_anchor_at, daily_time_local=daily_time_local,
                   timezone_name=timezone_name, window_before_minutes=window_before_minutes,
                   one_shot_at=one_shot_at)
    with open_queue_db(db_path) as connection, transaction(connection):
        return apply_create(connection, payload, now)


def _cancel_unleased(connection: sqlite3.Connection, rule_id: str,
                     now: datetime, reason: str, automatic_only: bool) -> None:
    query = "SELECT id FROM task_instances WHERE definition_id=? AND status IN ('future','ready')"
    if automatic_only:
        query += " AND origin IN ('scheduled','one_shot')"
    for item in connection.execute(query, (rule_id,)).fetchall():
        connection.execute(
            "UPDATE task_instances SET status='cancelled',last_error=?,updated_at=? WHERE id=?",
            (reason, stamp(now), item["id"]),
        )
        event(connection, "instance", item["id"], "cancelled", now, reason, actor="admin")


def apply_update(connection: sqlite3.Connection, rule_id: str, changes: dict,
                 now: datetime, expected_version: int | None = None) -> None:
    allowed = {"title", "instructions", "schedule_kind", "priority", "miss_policy",
               "max_lateness_minutes", "window_before_minutes", "lease_seconds",
               "max_attempts", "interval_minutes", "interval_anchor_at",
               "daily_time_local", "timezone_name", "one_shot_at", "is_active"}
    if not changes or set(changes) - allowed:
        raise QueueAdminError("No valid definition changes were provided.")
    old = connection.execute("SELECT * FROM task_definitions WHERE id=?", (rule_id,)).fetchone()
    if old is None or old["archived_at"] is not None:
        raise QueueAdminError("Unknown or archived rule.")
    if expected_version is not None and old["version"] != expected_version:
        raise QueueAdminError("Rule version conflict.")
    merged = dict(old)
    merged["timezone_name"] = merged["timezone"]
    merged.update(changes)
    data = _settings(merged["title"], merged["instructions"], merged["schedule_kind"],
                     merged["priority"], merged["miss_policy"],
                     merged["max_lateness_minutes"], merged["lease_seconds"],
                     merged["max_attempts"], merged["interval_minutes"],
                     merged["interval_anchor_at"], merged["daily_time_local"],
                     merged["timezone_name"], now, merged["window_before_minutes"],
                     merged["one_shot_at"])
    if merged["is_active"] not in (0, 1, True, False):
        raise QueueAdminError("is_active must be a boolean.")
    active, was_active = bool(merged["is_active"]), bool(old["is_active"])
    schedule_fields = {"schedule_kind", "interval_minutes", "interval_anchor_at",
                       "daily_time_local", "timezone", "one_shot_at"}
    schedule_changed = any(data[k] != old[k] for k in schedule_fields)
    if (schedule_changed and data["one_shot_at"] is not None and active
            and now > parse(data["one_shot_at"]) + timedelta(
                minutes=data["max_lateness_minutes"])):
        raise QueueAdminError("One-shot window has already closed.")
    if old["one_shot_at"] != data["one_shot_at"]:
        claimed = connection.execute(
            """SELECT 1 FROM task_instances WHERE definition_id=? AND origin='one_shot'
               AND attempt_count>0 LIMIT 1""", (rule_id,),
        ).fetchone()
        if claimed:
            raise QueueAdminError("Cannot move a one-shot rule after claim.")
    if active == was_active and all(data[k] == old[k] for k in data):
        raise QueueAdminError("Rule update has no effect.")
    if not active and was_active:
        _cancel_unleased(connection, rule_id, now, "rule_paused", True)
    elif schedule_changed:
        for item in connection.execute(
            """SELECT * FROM task_instances WHERE definition_id=?
               AND origin IN ('scheduled','one_shot') AND status IN ('future','ready')
               AND attempt_count=0""", (rule_id,),
        ).fetchall():
            target = parse(item["scheduled_at"])
            if item["origin"] == "one_shot":
                still_scheduled = data["one_shot_at"] == item["scheduled_at"]
            else:
                still_scheduled = (data["schedule_kind"] != ScheduleKind.MANUAL
                    and (data["schedule_kind"] != ScheduleKind.INTERVAL
                         or target >= parse(data["interval_anchor_at"]))
                    and _occurrence(data, target) == target)
            if still_scheduled:
                continue
            connection.execute(
                """UPDATE task_instances SET status='cancelled',last_error='schedule_changed',
                   updated_at=? WHERE id=?""", (stamp(now), item["id"]),
            )
            event(connection, "instance", item["id"], "cancelled", now,
                  "schedule_changed", actor="admin")
    connection.execute(
        """UPDATE task_definitions SET title=?,instructions=?,is_active=?,priority=?,
           schedule_kind=?,interval_minutes=?,interval_anchor_at=?,daily_time_local=?,
           timezone=?,miss_policy=?,max_lateness_minutes=?,window_before_minutes=?,
           lease_seconds=?,max_attempts=?,one_shot_at=?,pending_coverage_start=?,
           next_scheduled_at=?,version=version+1,updated_at=? WHERE id=?""",
        (data["title"], data["instructions"], int(active), data["priority"],
         data["schedule_kind"], data["interval_minutes"], data["interval_anchor_at"],
         data["daily_time_local"], data["timezone"], data["miss_policy"],
         data["max_lateness_minutes"], data["window_before_minutes"],
         data["lease_seconds"], data["max_attempts"], data["one_shot_at"],
         None if schedule_changed or active != was_active else old["pending_coverage_start"],
         None if schedule_changed or active != was_active else old["next_scheduled_at"],
         stamp(now), rule_id),
    )
    # Unstarted triggers use the current rule too, but keep their manual timing
    # and run_late policy. Retries of previously claimed work retain their snapshot.
    connection.execute(
        """UPDATE task_instances SET definition_version=?,title_snapshot=?,
           instructions_snapshot=?,priority_snapshot=?,lease_seconds_snapshot=?,
           max_attempts_snapshot=?,updated_at=? WHERE definition_id=?
           AND origin='manual' AND status IN ('future','ready') AND attempt_count=0""",
        (old["version"] + 1, data["title"], data["instructions"], data["priority"],
         data["lease_seconds"], data["max_attempts"], stamp(now), rule_id),
    )
    if active:
        for item in connection.execute(
            """SELECT * FROM task_instances WHERE definition_id=?
               AND origin IN ('scheduled','one_shot') AND status IN ('future','ready')
               AND attempt_count=0""", (rule_id,),
        ).fetchall():
            target = parse(item["scheduled_at"])
            start, end = window_for(data, target)
            coverage_start = item["coverage_start"]
            if schedule_changed and item["origin"] == "scheduled":
                # Recompute the regular interval, retaining any coalesced coverage.
                previous = stamp(previous_occurrence(data, target))
                old_previous = stamp(previous_occurrence(old, target))
                coverage_start = (min(previous, coverage_start)
                                  if coverage_start and coverage_start < old_previous
                                  else previous)
            version = old["version"] + 1
            connection.execute(
                """UPDATE task_instances SET definition_version=?,occurrence_key=?,
                   title_snapshot=?,instructions_snapshot=?,priority_snapshot=?,
                   miss_policy_snapshot=?,lease_seconds_snapshot=?,max_attempts_snapshot=?,
                   window_start_at=?,window_end_at=?,ready_at=?,coverage_start=?,
                   status=?,updated_at=? WHERE id=?""",
                (version, f'{version}:{stamp(target)}', data["title"], data["instructions"],
                 data["priority"], data["miss_policy"], data["lease_seconds"],
                 data["max_attempts"], stamp(start), stamp(end), stamp(start),
                 coverage_start, "ready" if start <= now else "future",
                 stamp(now), item["id"]),
            )
        if not was_active:
            _initialize_schedule(connection, rule_id, now, resume=True)
        elif schedule_changed:
            _initialize_schedule(connection, rule_id, now)
        else:
            if data["window_before_minutes"] != old["window_before_minutes"]:
                fill_schedule(connection, now, rule_id)
            reconcile(connection, now)
    event(connection, "definition", rule_id,
          "paused" if not active and was_active else "resumed" if active and not was_active
          else "updated", now, actor="admin")


def update_definition(rule_id: str, changes: dict, db_path: Path | None = None,
                      now: datetime | None = None, expected_version: int | None = None) -> None:
    now = utc(now or datetime.now(timezone.utc))
    with open_queue_db(db_path) as connection, transaction(connection):
        apply_update(connection, rule_id, changes, now, expected_version)


def apply_archive(connection: sqlite3.Connection, rule_id: str, now: datetime,
                  expected_version: int | None = None) -> None:
    old = connection.execute("SELECT * FROM task_definitions WHERE id=?", (rule_id,)).fetchone()
    if old is None or old["archived_at"] is not None:
        raise QueueAdminError("Unknown or archived rule.")
    if expected_version is not None and expected_version != old["version"]:
        raise QueueAdminError("Rule version conflict.")
    _cancel_unleased(connection, rule_id, now, "rule_archived", False)
    connection.execute(
        """UPDATE task_definitions SET is_active=0,archived_at=?,next_scheduled_at=NULL,
           pending_coverage_start=NULL,version=version+1,updated_at=? WHERE id=?""",
        (stamp(now), stamp(now), rule_id),
    )
    event(connection, "definition", rule_id, "archived", now, actor="admin")


def archive_definition(rule_id: str, db_path: Path | None = None,
                       now: datetime | None = None, expected_version: int | None = None) -> None:
    now = utc(now or datetime.now(timezone.utc))
    with open_queue_db(db_path) as connection, transaction(connection):
        apply_archive(connection, rule_id, now, expected_version)


def apply_trigger(connection: sqlite3.Connection, rule_id: str, now: datetime) -> str:
    rule = connection.execute("SELECT * FROM task_definitions WHERE id=?", (rule_id,)).fetchone()
    if rule is None or not rule["is_active"] or rule["archived_at"] is not None:
        raise QueueAdminError("Cannot run a paused or archived rule.")
    task_id = uuid4().hex
    connection.execute(
        """INSERT INTO task_instances
           (id,definition_id,definition_version,occurrence_key,title_snapshot,
            instructions_snapshot,priority_snapshot,scheduled_at,ready_at,window_start_at,
            origin,miss_policy_snapshot,lease_seconds_snapshot,max_attempts_snapshot,
            status,created_at,updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (task_id, rule_id, rule["version"], f"manual:{task_id}", rule["title"],
         rule["instructions"], rule["priority"], stamp(now), stamp(now), stamp(now),
         "manual", "run_late", rule["lease_seconds"], rule["max_attempts"],
         "ready", stamp(now), stamp(now)),
    )
    event(connection, "instance", task_id, "manual_trigger", now, actor="admin")
    return task_id


def trigger_definition(rule_id: str, db_path: Path | None = None,
                       now: datetime | None = None) -> str:
    now = utc(now or datetime.now(timezone.utc))
    with open_queue_db(db_path) as connection, transaction(connection):
        return apply_trigger(connection, rule_id, now)


def apply_cancel(connection: sqlite3.Connection, task_id: str, now: datetime) -> None:
    row = connection.execute("SELECT * FROM task_instances WHERE id=?", (task_id,)).fetchone()
    if row is None or row["status"] not in ("future", "ready", "leased"):
        raise QueueAdminError("Only pending or leased tasks can be cancelled.")
    if row["lease_token"]:
        connection.execute(
            "UPDATE task_attempts SET completed_at=?,outcome='cancelled' WHERE lease_token=? AND completed_at IS NULL",
            (stamp(now), row["lease_token"]),
        )
    connection.execute(
        """UPDATE task_instances SET status='cancelled',lease_token=NULL,
           lease_expires_at=NULL,updated_at=? WHERE id=?""", (stamp(now), task_id),
    )
    event(connection, "instance", task_id, "cancelled", now, actor="admin")


def cancel_instance(task_id: str, db_path: Path | None = None,
                    now: datetime | None = None) -> None:
    now = utc(now or datetime.now(timezone.utc))
    with open_queue_db(db_path) as connection, transaction(connection):
        apply_cancel(connection, task_id, now)


def apply_retry(connection: sqlite3.Connection, task_id: str, now: datetime) -> str:
    old = connection.execute("SELECT * FROM task_instances WHERE id=?", (task_id,)).fetchone()
    if old is None or old["status"] not in ("failed", "cancelled"):
        raise QueueAdminError("Only failed or cancelled tasks can be retried.")
    rule = connection.execute("SELECT * FROM task_definitions WHERE id=?", (old["definition_id"],)).fetchone()
    if not rule["is_active"] or rule["archived_at"] is not None:
        raise QueueAdminError("Cannot retry a task from a paused or archived rule.")
    new_id = uuid4().hex
    connection.execute(
        """INSERT INTO task_instances
           (id,definition_id,definition_version,occurrence_key,title_snapshot,
            instructions_snapshot,priority_snapshot,scheduled_at,ready_at,window_start_at,
            origin,miss_policy_snapshot,lease_seconds_snapshot,max_attempts_snapshot,
            coverage_start,coverage_end,status,retry_of_id,created_at,updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (new_id, old["definition_id"], old["definition_version"],
         f"retry:{task_id}:{new_id}", old["title_snapshot"],
         old["instructions_snapshot"], old["priority_snapshot"], stamp(now),
         stamp(now), stamp(now), "manual_retry", "run_late",
         old["lease_seconds_snapshot"] or rule["lease_seconds"],
         old["max_attempts_snapshot"] or rule["max_attempts"],
         old["coverage_start"], old["coverage_end"], "ready", task_id,
         stamp(now), stamp(now)),
    )
    event(connection, "instance", new_id, "manual_retry", now,
          f"Retry of {task_id}", actor="admin")
    return new_id


def retry_instance(task_id: str, db_path: Path | None = None,
                   now: datetime | None = None) -> str:
    now = utc(now or datetime.now(timezone.utc))
    with open_queue_db(db_path) as connection, transaction(connection):
        return apply_retry(connection, task_id, now)


def list_definitions(db_path: Path | None = None) -> list[dict]:
    with open_queue_db(db_path) as connection:
        return [{**dict(row), "window_after_minutes": row["max_lateness_minutes"]}
                for row in connection.execute(
            """SELECT d.*,
               (SELECT MIN(i.scheduled_at) FROM task_instances i
                WHERE i.definition_id=d.id AND i.status IN ('future','ready','leased')) AS next_visible_at
               FROM task_definitions d ORDER BY d.priority DESC,d.title,d.id"""
        ).fetchall()]


def get_definition(rule_id: str, db_path: Path | None = None) -> dict:
    with open_queue_db(db_path) as connection:
        row = connection.execute("SELECT * FROM task_definitions WHERE id=?", (rule_id,)).fetchone()
        if row is None:
            raise QueueAdminError("Unknown definition.")
        events = connection.execute(
            "SELECT * FROM task_events WHERE entity_type='definition' AND entity_id=? ORDER BY id",
            (rule_id,),
        ).fetchall()
        return {"definition": {**dict(row),
                               "window_after_minutes": row["max_lateness_minutes"]},
                "events": [dict(item) for item in events]}


def list_instances(db_path: Path | None = None, status: str | None = None,
                   now: datetime | None = None) -> list[dict]:
    refresh_queue(now, db_path)
    with open_queue_db(db_path) as connection:
        if status is not None and status not in {item.value for item in InstanceStatus}:
            raise QueueAdminError("Unknown instance status.")
        query = "SELECT * FROM task_instances"
        if status is not None:
            query += " WHERE status=?"
        query += " ORDER BY scheduled_at DESC,id DESC"
        return [dict(row) for row in connection.execute(query, (status,) if status else ()).fetchall()]


def list_definition_summaries(is_active: bool | None, limit: int, offset: int,
                              db_path: Path | None = None) -> list[dict]:
    """MCP catalog: metadata only; never load instruction bodies."""
    query = """SELECT d.id,d.title,d.is_active,d.priority,d.schedule_kind,
                      d.interval_minutes,d.daily_time_local,d.timezone,d.one_shot_at,
                      d.archived_at,d.version,d.next_scheduled_at,
                      (SELECT MIN(i.scheduled_at) FROM task_instances i
                       WHERE i.definition_id=d.id
                         AND i.status IN ('future','ready','leased')) AS next_visible_at
               FROM task_definitions d"""
    params: list = []
    if is_active is not None:
        query += " WHERE d.is_active=? AND d.archived_at IS NULL"
        params.append(int(is_active))
    query += " ORDER BY d.priority DESC,d.title,d.id LIMIT ? OFFSET ?"
    with open_queue_db(db_path) as connection:
        return [dict(row) for row in connection.execute(query, (*params, limit, offset))]


def list_instance_summaries(status: str | None, limit: int, offset: int,
                            db_path: Path | None = None,
                            now: datetime | None = None) -> list[dict]:
    """MCP catalog: metadata only; never load prompts, results or errors."""
    if status is not None and status not in {item.value for item in InstanceStatus}:
        raise QueueAdminError("Unknown instance status.")
    refresh_queue(now, db_path)
    query = """SELECT id,definition_id,definition_version,title_snapshot,status,
                      scheduled_at,coverage_start,coverage_end,attempt_count
               FROM task_instances"""
    params: list = []
    if status is not None:
        query += " WHERE status=?"
        params.append(status)
    query += " ORDER BY scheduled_at DESC,id DESC LIMIT ? OFFSET ?"
    with open_queue_db(db_path) as connection:
        return [dict(row) for row in connection.execute(query, (*params, limit, offset))]


def get_instance(task_id: str, db_path: Path | None = None) -> dict:
    with open_queue_db(db_path) as connection:
        row = connection.execute("SELECT * FROM task_instances WHERE id=?", (task_id,)).fetchone()
        if row is None:
            raise QueueAdminError("Unknown instance.")
        attempts = connection.execute(
            "SELECT * FROM task_attempts WHERE instance_id=? ORDER BY attempt_number", (task_id,),
        ).fetchall()
        events = connection.execute(
            "SELECT * FROM task_events WHERE entity_type='instance' AND entity_id=? ORDER BY id",
            (task_id,),
        ).fetchall()
        return {"instance": dict(row), "attempts": [dict(item) for item in attempts],
                "events": [dict(item) for item in events]}
