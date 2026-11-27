"""SQLite storage and migrations for the durable task queue."""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import sqlite3
from typing import Iterator


SCHEMA_VERSION = 3

SCHEMA_V1 = (
    """
    CREATE TABLE task_definitions (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL CHECK (length(trim(title)) > 0),
        instructions TEXT NOT NULL CHECK (length(trim(instructions)) > 0),
        is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
        priority INTEGER NOT NULL DEFAULT 5 CHECK (priority BETWEEN 0 AND 9),
        schedule_kind TEXT NOT NULL CHECK (schedule_kind IN ('manual', 'interval', 'daily')),
        interval_minutes INTEGER CHECK (interval_minutes > 0),
        interval_anchor_at TEXT,
        daily_time_local TEXT,
        timezone TEXT,
        miss_policy TEXT NOT NULL DEFAULT 'run_late'
            CHECK (miss_policy IN ('skip', 'merge_next', 'run_late')),
        max_lateness_minutes INTEGER NOT NULL DEFAULT 30 CHECK (max_lateness_minutes >= 0),
        lease_seconds INTEGER NOT NULL DEFAULT 1800 CHECK (lease_seconds > 0),
        max_attempts INTEGER NOT NULL DEFAULT 3 CHECK (max_attempts > 0),
        next_scheduled_at TEXT,
        pending_coverage_start TEXT,
        version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        CHECK (
            (schedule_kind = 'manual' AND interval_minutes IS NULL
                AND interval_anchor_at IS NULL AND daily_time_local IS NULL)
            OR (schedule_kind = 'interval' AND interval_minutes IS NOT NULL
                AND interval_anchor_at IS NOT NULL AND daily_time_local IS NULL)
            OR (schedule_kind = 'daily' AND interval_minutes IS NULL
                AND interval_anchor_at IS NULL AND daily_time_local IS NOT NULL
                AND timezone IS NOT NULL)
        )
    )
    """,
    """
    CREATE TABLE task_instances (
        id TEXT PRIMARY KEY,
        definition_id TEXT NOT NULL REFERENCES task_definitions(id) ON DELETE RESTRICT,
        definition_version INTEGER NOT NULL CHECK (definition_version > 0),
        occurrence_key TEXT NOT NULL,
        title_snapshot TEXT NOT NULL,
        instructions_snapshot TEXT NOT NULL,
        priority_snapshot INTEGER NOT NULL CHECK (priority_snapshot BETWEEN 0 AND 9),
        scheduled_at TEXT NOT NULL,
        ready_at TEXT NOT NULL,
        coverage_start TEXT,
        coverage_end TEXT,
        status TEXT NOT NULL CHECK (status IN
            ('future', 'ready', 'leased', 'succeeded', 'failed',
             'skipped', 'merged', 'cancelled')),
        attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
        lease_token TEXT,
        lease_expires_at TEXT,
        result_json TEXT,
        last_error TEXT,
        retry_of_id TEXT REFERENCES task_instances(id) ON DELETE RESTRICT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE (definition_id, occurrence_key),
        CHECK ((lease_token IS NULL) = (lease_expires_at IS NULL)),
        CHECK (status != 'leased' OR lease_token IS NOT NULL)
    )
    """,
    """
    CREATE TABLE task_attempts (
        id INTEGER PRIMARY KEY,
        instance_id TEXT NOT NULL REFERENCES task_instances(id) ON DELETE RESTRICT,
        attempt_number INTEGER NOT NULL CHECK (attempt_number > 0),
        lease_token TEXT NOT NULL UNIQUE,
        claimed_at TEXT NOT NULL,
        completed_at TEXT,
        outcome TEXT CHECK (outcome IN ('succeeded', 'failed', 'expired', 'cancelled')),
        result_json TEXT,
        error TEXT,
        report_hash TEXT,
        report_response_json TEXT,
        UNIQUE (instance_id, attempt_number)
    )
    """,
    """
    CREATE TABLE task_events (
        id INTEGER PRIMARY KEY,
        occurred_at TEXT NOT NULL,
        entity_type TEXT NOT NULL CHECK (entity_type IN ('definition', 'instance')),
        entity_id TEXT NOT NULL,
        action TEXT NOT NULL,
        reason TEXT,
        actor TEXT NOT NULL CHECK (actor IN ('scheduler', 'agent', 'admin')),
        data_json TEXT
    )
    """,
    "CREATE INDEX task_instances_ready ON task_instances(status, ready_at, priority_snapshot)",
    "CREATE INDEX task_instances_definition ON task_instances(definition_id, scheduled_at)",
    "CREATE INDEX task_instances_lease ON task_instances(status, lease_expires_at)",
    "CREATE INDEX task_events_entity ON task_events(entity_type, entity_id, occurred_at)",
)


SCHEMA_V2 = (
    "ALTER TABLE task_definitions ADD COLUMN window_before_minutes INTEGER NOT NULL DEFAULT 0 CHECK (window_before_minutes >= 0)",
    "ALTER TABLE task_definitions ADD COLUMN one_shot_at TEXT",
    "ALTER TABLE task_definitions ADD COLUMN archived_at TEXT",
    "ALTER TABLE task_instances ADD COLUMN window_start_at TEXT",
    "ALTER TABLE task_instances ADD COLUMN window_end_at TEXT",
    "ALTER TABLE task_instances ADD COLUMN origin TEXT CHECK (origin IN ('scheduled', 'one_shot', 'manual', 'manual_retry'))",
    "ALTER TABLE task_instances ADD COLUMN miss_policy_snapshot TEXT CHECK (miss_policy_snapshot IN ('skip', 'merge_next', 'run_late'))",
    "ALTER TABLE task_instances ADD COLUMN lease_seconds_snapshot INTEGER CHECK (lease_seconds_snapshot > 0)",
    "ALTER TABLE task_instances ADD COLUMN max_attempts_snapshot INTEGER CHECK (max_attempts_snapshot > 0)",
    """CREATE TABLE task_change_proposals (
        id TEXT PRIMARY KEY,
        operation TEXT NOT NULL,
        target_id TEXT,
        payload_json TEXT NOT NULL,
        payload_hash TEXT NOT NULL,
        expected_version INTEGER,
        proposer TEXT NOT NULL,
        idempotency_key TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'rejected', 'stale')),
        created_at TEXT NOT NULL,
        decided_at TEXT,
        decision_source TEXT CHECK (decision_source IN ('manual', 'auto')),
        reviewer_session_id TEXT,
        reason TEXT,
        result_json TEXT,
        UNIQUE (proposer, idempotency_key)
    )""",
    "CREATE INDEX task_proposals_status ON task_change_proposals(status, created_at)",
    """CREATE TABLE queue_security (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        pin_salt TEXT,
        pin_verifier TEXT,
        pin_version INTEGER NOT NULL DEFAULT 0,
        login_failures INTEGER NOT NULL DEFAULT 0,
        locked_until TEXT,
        auto_approve_until TEXT,
        auto_approve_session_id TEXT
    )""",
    "INSERT INTO queue_security(id) VALUES (1)",
    """CREATE TABLE queue_security_events (
        id INTEGER PRIMARY KEY,
        occurred_at TEXT NOT NULL,
        action TEXT NOT NULL,
        session_id TEXT
    )""",
)


def queue_db_path() -> Path:
    """Return the configured database path without creating it."""
    return Path(os.environ.get("QUEUE_DB_PATH", Path.home() / "queue.sqlite3"))


@contextmanager
def transaction(connection: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Serialize a read-modify-write operation across queue connections."""
    connection.execute("BEGIN IMMEDIATE")
    try:
        yield connection
    except BaseException:
        connection.rollback()
        raise
    else:
        connection.commit()


def migrate(connection: sqlite3.Connection) -> None:
    """Apply pending migrations; reject a database from a newer app version."""
    with transaction(connection):
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise RuntimeError(f"Queue database version {version} is newer than {SCHEMA_VERSION}.")
        if version == 0:
            for statement in SCHEMA_V1:
                connection.execute(statement)
            version = 1
        if version == 1:
            for statement in SCHEMA_V2:
                connection.execute(statement)
            # Active rows need immutable execution settings. Finished history is untouched.
            rows = connection.execute(
                """SELECT i.id, i.occurrence_key, i.retry_of_id, i.scheduled_at,
                          d.max_lateness_minutes, d.miss_policy, d.lease_seconds,
                          d.max_attempts
                   FROM task_instances i JOIN task_definitions d ON d.id=i.definition_id
                   WHERE i.status IN ('future', 'ready', 'leased')"""
            ).fetchall()
            from datetime import datetime, timedelta
            for row in rows:
                key = row["occurrence_key"]
                if row["retry_of_id"] or key.startswith("retry:"):
                    origin = "manual_retry"
                elif key.startswith("manual:"):
                    origin = "manual"
                elif ":" in key and key.split(":", 1)[0].isdigit():
                    origin = "scheduled"
                else:
                    raise RuntimeError(f"Unknown active occurrence key on instance {row['id']}")
                end = (datetime.fromisoformat(row["scheduled_at"])
                       + timedelta(minutes=row["max_lateness_minutes"])).isoformat() if origin == "scheduled" else None
                connection.execute(
                    """UPDATE task_instances SET window_start_at=?, window_end_at=?,
                       origin=?, miss_policy_snapshot=?, lease_seconds_snapshot=?,
                       max_attempts_snapshot=? WHERE id=?""",
                    (row["scheduled_at"], end, origin,
                     row["miss_policy"] if origin == "scheduled" else "run_late",
                     row["lease_seconds"], row["max_attempts"], row["id"]),
                )
            connection.execute(
                """CREATE UNIQUE INDEX task_instances_active_automatic_target
                   ON task_instances(definition_id, scheduled_at)
                   WHERE origin IN ('scheduled', 'one_shot')
                     AND status IN ('future', 'ready', 'leased')"""
            )
            connection.execute("PRAGMA user_version = 2")
            version = 2
        if version == 2:
            connection.execute('ALTER TABLE task_definitions ADD COLUMN "group" TEXT')
            connection.execute("ALTER TABLE task_definitions ADD COLUMN execution_version INTEGER NOT NULL DEFAULT 1 CHECK (execution_version > 0)")
            connection.execute("UPDATE task_definitions SET execution_version=version")
            connection.execute("PRAGMA user_version = 3")


@contextmanager
def open_queue_db(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    """Open a configured queue DB, creating or migrating it as needed."""
    path = path or queue_db_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=5, isolation_level=None)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        migrate(connection)
        yield connection
    finally:
        connection.close()
