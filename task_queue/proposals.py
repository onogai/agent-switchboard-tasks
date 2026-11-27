"""Channel-independent proposal storage and atomic decisions."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from .admin import (QueueAdminError, _settings, apply_archive, apply_cancel,
                    apply_create, apply_retry, apply_trigger, apply_update,
                    normalize_group, _updated_settings, _execution_changed, _schedule_changed)
from .db import open_queue_db, transaction
from .models import RULE_CREATE_DEFAULTS
from .scheduler import parse, stamp, utc

OPERATIONS = {"create_rule", "update_rule", "archive_rule", "run_rule",
              "cancel_instance", "retry_instance"}
RULE_OPERATIONS = {"update_rule", "archive_rule", "run_rule"}


def _canonical(value: dict) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                      allow_nan=False)


def _normalize_rule_fields(payload: dict) -> dict:
    payload = dict(payload)
    if "group" in payload:
        payload["group"] = normalize_group(payload["group"])
    if "timezone" in payload:
        if "timezone_name" in payload and payload["timezone_name"] != payload["timezone"]:
            raise QueueAdminError("timezone and legacy timezone_name disagree; use timezone.")
        payload["timezone_name"] = payload.pop("timezone")
    if "window_after_minutes" in payload:
        if ("max_lateness_minutes" in payload
                and payload["max_lateness_minutes"] != payload["window_after_minutes"]):
            raise QueueAdminError("max_lateness_minutes and legacy window_after_minutes disagree; "
                                  "use max_lateness_minutes.")
        payload["max_lateness_minutes"] = payload.pop("window_after_minutes")
    if payload.get("schedule_kind") == "one_shot":
        if not payload.get("one_shot_at"):
            raise QueueAdminError("One-shot rules need one_shot_at.")
        payload["schedule_kind"] = "manual"
    return payload


def _row(row: sqlite3.Row) -> dict:
    data = dict(row)
    data["proposal_id"] = data["id"]
    data["payload"] = json.loads(data.pop("payload_json"))
    data["result"] = json.loads(data.pop("result_json")) if data["result_json"] else None
    return data


def _impact(connection: sqlite3.Connection, data: dict) -> dict | None:
    if data["status"] != "pending" or not data["target_id"]:
        return None
    if data["operation"] == "update_rule" and "group" in data["payload"]:
        rule = connection.execute("SELECT * FROM task_definitions WHERE id=?", (data["target_id"],)).fetchone()
        if rule is not None and rule["archived_at"] is None:
            try:
                settings, active = _updated_settings(rule, data["payload"], datetime.now(timezone.utc))
                if not _execution_changed(rule, settings, active):
                    return {"metadata_only": True}
            except QueueAdminError:
                pass  # Invalid edits are handled by the normal proposal validation.
    if data["operation"] in {"update_rule", "archive_rule"}:
        counts = connection.execute(
            """SELECT
               SUM(CASE WHEN origin IN ('scheduled','one_shot')
                         AND status IN ('future','ready') AND attempt_count=0
                        THEN 1 ELSE 0 END) AS unstarted,
               SUM(CASE WHEN status='leased' THEN 1 ELSE 0 END) AS leased,
               SUM(CASE WHEN status IN ('future','ready') THEN 1 ELSE 0 END) AS unleased,
               SUM(CASE WHEN origin IN ('scheduled','one_shot') AND status='ready'
                         AND attempt_count>0 THEN 1 ELSE 0 END) AS queued_retries
               FROM task_instances WHERE definition_id=?""", (data["target_id"],)
        ).fetchone()
        return {key: counts[key] or 0 for key in counts.keys()}
    if data["operation"] in {"cancel_instance", "retry_instance"}:
        row = connection.execute("SELECT status FROM task_instances WHERE id=?",
                                 (data["target_id"],)).fetchone()
        return {"current_status": row["status"] if row else None}
    return None


def _view(connection: sqlite3.Connection, row: sqlite3.Row) -> dict:
    data = _row(row)
    data["impact"] = _impact(connection, data)
    return data


def _apply(connection: sqlite3.Connection, row: sqlite3.Row, now: datetime):
    operation = row["operation"]
    payload = json.loads(row["payload_json"])
    target = row["target_id"]
    version = row["expected_version"]
    if operation in RULE_OPERATIONS:
        rule = connection.execute("SELECT version FROM task_definitions WHERE id=?", (target,)).fetchone()
        if rule is None or rule["version"] != version:
            raise QueueAdminError("Rule version conflict.")
    if operation == "create_rule":
        return {"id": apply_create(connection, payload, now)}
    if operation == "update_rule":
        apply_update(connection, target, payload, now, version)
        return {"id": target}
    if operation == "archive_rule":
        apply_archive(connection, target, now, version)
        return {"id": target}
    if operation == "run_rule":
        return {"id": apply_trigger(connection, target, now)}
    if operation == "cancel_instance":
        apply_cancel(connection, target, now)
        return {"id": target}
    if operation == "retry_instance":
        return {"id": apply_retry(connection, target, now)}
    raise QueueAdminError("Unknown proposal operation.")


def _decide(connection: sqlite3.Connection, row: sqlite3.Row, approve: bool,
            source: str, session_id: str, now: datetime) -> dict:
    if row["status"] != "pending":
        return _view(connection, row)
    if not approve:
        status, reason, result = "rejected", None, None
    else:
        connection.execute("SAVEPOINT proposal_apply")
        try:
            result = _apply(connection, row, now)
            connection.execute("RELEASE SAVEPOINT proposal_apply")
            status, reason = "approved", None
        except QueueAdminError as exc:
            connection.execute("ROLLBACK TO SAVEPOINT proposal_apply")
            connection.execute("RELEASE SAVEPOINT proposal_apply")
            status, reason, result = "stale", str(exc), None
    connection.execute(
        """UPDATE task_change_proposals SET status=?,decided_at=?,decision_source=?,
           reviewer_session_id=?,reason=?,result_json=? WHERE id=? AND status='pending'""",
        (status, stamp(now), source, session_id, reason,
         _canonical(result) if result is not None else None, row["id"]),
    )
    return _view(connection, connection.execute(
        "SELECT * FROM task_change_proposals WHERE id=?", (row["id"],)
    ).fetchone())


def submit_proposal(operation: str, payload: dict, target_id: str | None,
                    expected_version: int | None, proposer: str,
                    idempotency_key: str, db_path: Path | None = None,
                    now: datetime | None = None) -> dict:
    fixed_now = now
    now = utc(now or datetime.now(timezone.utc))
    if operation not in OPERATIONS or not isinstance(payload, dict):
        raise QueueAdminError("Invalid proposal operation or payload.")
    if operation in {"create_rule", "update_rule"}:
        payload = _normalize_rule_fields(payload)
    if not proposer or not idempotency_key or len(idempotency_key) > 128:
        raise QueueAdminError("Proposer and bounded idempotency_key are required.")
    if operation == "create_rule":
        if target_id is not None or expected_version is not None:
            raise QueueAdminError("Create proposal cannot name an existing rule.")
        required = {"title", "instructions"}
        unknown = set(payload) - RULE_CREATE_DEFAULTS.keys() - required - {"group"}
        missing = required - payload.keys()
        if unknown or missing:
            details = []
            if unknown:
                details.append("Unknown fields: " + ", ".join(sorted(unknown)))
            if missing:
                details.append("Required fields: " + ", ".join(sorted(missing)))
            if "is_active" in unknown:
                details.append("New rules are active; use update_rule to pause")
            raise QueueAdminError("; ".join(details))
        payload = {**RULE_CREATE_DEFAULTS, **payload}
        _settings(now=now, **payload)
    elif operation in RULE_OPERATIONS:
        if not target_id or type(expected_version) is not int or expected_version <= 0:
            raise QueueAdminError("Rule target and expected_version are required.")
        if operation == "update_rule":
            unknown = set(payload) - RULE_CREATE_DEFAULTS.keys() - {
                "title", "instructions", "is_active", "group"}
            if unknown:
                raise QueueAdminError("Unknown update fields: " + ", ".join(sorted(unknown)))
            if not payload:
                raise QueueAdminError("changes must contain at least one field.")
        if operation != "update_rule" and payload:
            raise QueueAdminError("This proposal takes no payload.")
    else:
        if not target_id or payload or expected_version is not None:
            raise QueueAdminError("Instance proposal needs only a target ID.")
    raw = _canonical(payload)
    fingerprint = sha256(_canonical({"operation": operation, "target": target_id,
                                   "version": expected_version,
                                   "payload": payload}).encode()).hexdigest()
    with open_queue_db(db_path) as connection, transaction(connection):
        if fixed_now is None:
            now = datetime.now(timezone.utc)
        existing = connection.execute(
            """SELECT * FROM task_change_proposals WHERE proposer=? AND idempotency_key=?""",
            (proposer, idempotency_key),
        ).fetchone()
        if existing is not None:
            if existing["payload_hash"] != fingerprint:
                raise QueueAdminError("Idempotency key was used for another proposal.")
            return _view(connection, existing)
        if operation in RULE_OPERATIONS:
            state = connection.execute(
                "SELECT is_active,archived_at FROM task_definitions WHERE id=?",
                (target_id,),
            ).fetchone()
            if state is None or state["archived_at"] is not None:
                raise QueueAdminError("Unknown or archived rule.")
            if operation == "run_rule" and not state["is_active"]:
                raise QueueAdminError("Cannot run a paused rule.")
        elif operation in {"cancel_instance", "retry_instance"}:
            state = connection.execute(
                """SELECT i.status,d.is_active,d.archived_at FROM task_instances i
                   JOIN task_definitions d ON d.id=i.definition_id WHERE i.id=?""",
                (target_id,),
            ).fetchone()
            if state is None:
                raise QueueAdminError("Unknown instance.")
            if operation == "cancel_instance" and state["status"] not in {
                    "future", "ready", "leased"}:
                raise QueueAdminError("Only pending or leased tasks can be cancelled.")
            if operation == "retry_instance" and (
                    state["status"] not in {"failed", "cancelled"}
                    or not state["is_active"] or state["archived_at"] is not None):
                raise QueueAdminError("Cannot retry this task from a paused or archived rule.")
        if operation == "update_rule":
            rule = connection.execute("SELECT * FROM task_definitions WHERE id=?",
                                      (target_id,)).fetchone()
            if rule is None:
                raise QueueAdminError("Unknown rule.")
            merged = dict(rule)
            merged["timezone_name"] = merged["timezone"]
            merged.update(payload)
            _settings(merged["title"], merged["instructions"], merged["schedule_kind"],
                      merged["priority"], merged["miss_policy"],
                      merged["max_lateness_minutes"], merged["lease_seconds"],
                      merged["max_attempts"], merged["interval_minutes"],
                      merged["interval_anchor_at"], merged["daily_time_local"],
                      merged["timezone_name"], now, merged["window_before_minutes"],
                      merged["one_shot_at"])
            if merged["is_active"] not in (0, 1, False, True):
                raise QueueAdminError("is_active must be a boolean.")
        identifier = uuid4().hex
        connection.execute(
            """INSERT INTO task_change_proposals
               (id,operation,target_id,payload_json,payload_hash,expected_version,
                proposer,idempotency_key,status,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (identifier, operation, target_id, raw, fingerprint, expected_version,
             proposer, idempotency_key, "pending", stamp(now)),
        )
        row = connection.execute("SELECT * FROM task_change_proposals WHERE id=?",
                                 (identifier,)).fetchone()
        security = connection.execute(
            "SELECT auto_approve_until,auto_approve_session_id FROM queue_security WHERE id=1"
        ).fetchone()
        if security["auto_approve_until"] and now < parse(security["auto_approve_until"]):
            from .managed_approval import auto_approval_authorized
            if auto_approval_authorized(security["auto_approve_session_id"]):
                return _decide(connection, row, True, "auto",
                               security["auto_approve_session_id"], now)
        return _view(connection, row)


def decide_proposal(proposal_id: str, approve: bool, reviewer_session_id: str,
                    db_path: Path | None = None, now: datetime | None = None) -> dict:
    now = utc(now or datetime.now(timezone.utc))
    if not reviewer_session_id:
        raise QueueAdminError("Authenticated reviewer session required.")
    with open_queue_db(db_path) as connection, transaction(connection):
        row = connection.execute("SELECT * FROM task_change_proposals WHERE id=?",
                                 (proposal_id,)).fetchone()
        if row is None:
            raise QueueAdminError("Unknown proposal.")
        return _decide(connection, row, approve, "manual", reviewer_session_id, now)


def get_proposal(proposal_id: str, db_path: Path | None = None) -> dict:
    with open_queue_db(db_path) as connection:
        row = connection.execute("SELECT * FROM task_change_proposals WHERE id=?",
                                 (proposal_id,)).fetchone()
        if row is None:
            raise QueueAdminError("Unknown proposal.")
        return _view(connection, row)


def list_proposals(db_path: Path | None = None, status: str | None = None,
                   limit: int = 50, offset: int = 0) -> list[dict]:
    if status is not None and status not in {"pending", "approved", "rejected", "stale"}:
        raise QueueAdminError("Unknown proposal status.")
    if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or offset < 0:
        raise QueueAdminError("Invalid proposal pagination.")
    with open_queue_db(db_path) as connection:
        query = "SELECT * FROM task_change_proposals"
        params: list = []
        if status:
            query += " WHERE status=?"
            params.append(status)
        query += " ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?"
        params.extend((limit, offset))
        return [_view(connection, row) for row in connection.execute(query, params).fetchall()]


def _review_presentation(connection: sqlite3.Connection, data: dict) -> dict:
    """HTTP review copy only; never changes a proposal or its decision."""
    operation, payload = data["operation"], data["payload"]
    target = data["target_id"]
    rule = None
    if operation == "create_rule":
        title = payload.get("title")
    elif operation in RULE_OPERATIONS:
        rule = connection.execute("SELECT * FROM task_definitions WHERE id=?", (target,)).fetchone()
        title = rule["title"] if rule else payload.get("title")
    else:
        instance = connection.execute("SELECT title_snapshot FROM task_instances WHERE id=?", (target,)).fetchone()
        title = instance["title_snapshot"] if instance else None

    def short(value):
        if value is None:
            return "—"
        text = str(value)
        return text if len(text) <= 80 else text[:77] + "..."

    labels = {"title": "title", "instructions": "instructions", "group": "group",
              "is_active": "active state", "schedule_kind": "schedule type",
              "interval_minutes": "interval (minutes)", "interval_anchor_at": "interval anchor",
              "daily_time_local": "daily time", "timezone_name": "time zone",
              "one_shot_at": "one-shot time", "priority": "priority",
              "miss_policy": "missed-run policy", "max_lateness_minutes": "late window (minutes)",
              "window_before_minutes": "early window (minutes)", "lease_seconds": "lease (seconds)",
              "max_attempts": "maximum attempts"}
    impact = data["impact"] or {}
    if operation == "create_rule":
        kind = "one-shot" if payload.get("one_shot_at") else payload.get("schedule_kind", "manual")
        summary = "Create rule: " + short(kind) + " schedule."
        if payload.get("daily_time_local"):
            summary += " Daily at " + short(payload["daily_time_local"]) + "."
        if payload.get("interval_minutes"):
            summary += " Every " + short(payload["interval_minutes"]) + " minutes."
        if payload.get("one_shot_at"):
            summary += " One shot at " + short(payload["one_shot_at"]) + "."
        if payload.get("timezone_name"):
            summary += " Time zone: " + short(payload["timezone_name"]) + "."
        effect = "Creates a rule and its current scheduled runs."
    elif operation == "update_rule":
        settings, active = None, None
        if rule is not None and rule["archived_at"] is None:
            try:
                settings, active = _updated_settings(rule, payload, datetime.now(timezone.utc))
            except QueueAdminError:
                pass
        changes = []
        if settings is not None:
            for column, value in settings.items():
                old = rule[column]
                if old == value:
                    continue
                label = labels.get("timezone_name" if column == "timezone" else column, column)
                if column == "instructions":
                    changes.append("update instructions")
                else:
                    changes.append(label + ": " + short(old) + " → " + short(value))
            if active != bool(rule["is_active"]):
                changes.append("enable rule" if active else "pause rule")
        else:
            changes = [labels.get(key, key) for key in payload]
        summary = "; ".join(changes) + "." if changes else "No effective changes."
        if rule is None or rule["archived_at"] is not None:
            effect = "Rule no longer available; approval may be stale."
        elif rule["version"] != data["expected_version"]:
            effect = "Rule version conflict; approval will be stale."
        elif settings is None:
            effect = "Proposed settings are no longer valid."
        elif not _execution_changed(rule, settings, active):
            effect = ("Updates organization only; scheduled tasks are unchanged."
                      if settings["group"] != rule["group"] else
                      "No effective rule changes; approval will be stale.")
        elif not active and bool(rule["is_active"]):
            effect = (f"Pausing will cancel {impact.get('unstarted', 0)} unleased automatic runs "
                      f"and {impact.get('queued_retries', 0)} pending automatic retries.")
        elif active and not bool(rule["is_active"]):
            effect = "Enables the rule and generates eligible scheduled runs."
        elif _schedule_changed(rule, settings):
            effect = (f"Rebuilds up to {impact.get('unstarted', 0)} automatic runs without attempts; "
                      "active leases remain.")
        else:
            effect = (f"Updates up to {impact.get('unstarted', 0)} automatic runs without attempts; "
                      f"{impact.get('queued_retries', 0)} pending retries retain their existing parameters.")
    elif operation == "archive_rule":
        summary = "Archive rule."
        effect = (f"Cancels {impact.get('unleased', 0)} unleased instances; "
                  f"{impact.get('leased', 0)} active leases will be preserved.")
    elif operation == "run_rule":
        summary, effect = "Run rule now.", "Creates one additional manual run."
    elif operation == "cancel_instance":
        summary = "Cancel task instance."
        effect = f"Cancels an instance in state {impact.get('current_status') or 'unknown'}."
    else:
        summary = "Retry task instance."
        effect = f"Creates a new manual retry for an instance in state {impact.get('current_status') or 'unknown'}."
    return {**data, "target_title": title or target or "New rule",
            "summary": summary, "impact_summary": effect if data["status"] == "pending" else None}


def review_proposals(db_path: Path | None = None, status: str | None = None,
                     limit: int = 50, offset: int = 0, count_only: bool = False) -> dict:
    """Read a consistent page and count; polling the count does not read payloads."""
    if status is not None and status not in {"pending", "approved", "rejected", "stale"}:
        raise QueueAdminError("Unknown proposal status.")
    if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or offset < 0:
        raise QueueAdminError("Invalid proposal pagination.")
    where, params = (" WHERE status=?", (status,)) if status else ("", ())
    with open_queue_db(db_path) as connection:
        connection.execute("BEGIN")
        total = connection.execute("SELECT COUNT(*) FROM task_change_proposals" + where, params).fetchone()[0]
        if count_only:
            return {"total": total}
        rows = connection.execute(
            "SELECT * FROM task_change_proposals" + where + " ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?",
            (*params, limit, offset)).fetchall()
        return {"total": total, "proposals": [
            _review_presentation(connection, _view(connection, row)) for row in rows]}


def auto_approval_state(db_path: Path | None = None,
                        now: datetime | None = None) -> dict:
    now = utc(now or datetime.now(timezone.utc))
    with open_queue_db(db_path) as connection:
        row = connection.execute("SELECT auto_approve_until FROM queue_security WHERE id=1").fetchone()
        until = row[0]
        from .managed_approval import auto_approval_authorized
        session = connection.execute(
            "SELECT auto_approve_session_id FROM queue_security WHERE id=1"
        ).fetchone()[0]
        enabled = bool(until and now < parse(until) and auto_approval_authorized(session))
        return {"enabled": enabled, "until": until if enabled else None}


def set_auto_approval(enabled: bool, session_id: str, db_path: Path | None = None,
                      now: datetime | None = None) -> dict:
    fixed_now = now
    now = utc(now or datetime.now(timezone.utc))
    if not session_id or type(enabled) is not bool:
        raise QueueAdminError("Authenticated session and boolean enabled are required.")
    if enabled:
        from .managed_approval import auto_approval_authorized
        if not auto_approval_authorized(session_id):
            raise QueueAdminError("Auto-approval authority is unavailable or session revoked.")
    with open_queue_db(db_path) as connection, transaction(connection):
        if fixed_now is None:
            now = datetime.now(timezone.utc)
        current_row = connection.execute(
            "SELECT auto_approve_until,auto_approve_session_id "
            "FROM queue_security WHERE id=1"
        ).fetchone()
        current = current_row["auto_approve_until"]
        if enabled and current and now < parse(current) and (
                current_row["auto_approve_session_id"] == session_id):
            return {"enabled": True, "until": current}
        until = stamp(now + timedelta(hours=1)) if enabled else None
        connection.execute(
            """UPDATE queue_security SET auto_approve_until=?,auto_approve_session_id=? WHERE id=1""",
            (until, session_id if enabled else None),
        )
        connection.execute(
            "INSERT INTO queue_security_events(occurred_at,action,session_id) VALUES (?,?,?)",
            (stamp(now), "auto_approval_enabled" if enabled else "auto_approval_disabled",
             session_id),
        )
    return {"enabled": enabled, "until": until}
