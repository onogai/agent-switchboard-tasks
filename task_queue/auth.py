"""Shell-owned PIN verifier and session revocation state.

The first open copies the existing Queue PIN verifier. The same pepper and
session secret remain valid; no plaintext PIN or new secret is needed.
"""

from __future__ import annotations

import os
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from getpass import getpass
from hashlib import scrypt
from hmac import compare_digest
from pathlib import Path
from secrets import token_bytes


logger = logging.getLogger(__name__)


def admin_db_path(queue_path: Path | None = None) -> Path:
    configured = os.environ.get("ADMIN_DB_PATH")
    if configured:
        return Path(configured)
    queue_path = queue_path or Path(os.environ.get("QUEUE_DB_PATH", "/home/ubuntu/queue.sqlite3"))
    return queue_path.with_name("admin.sqlite3")


def _connect(path: Path):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.exists() and path.is_symlink():
        raise ValueError("Admin database path must not be a symlink")
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout=10000")
    db.execute("PRAGMA journal_mode=WAL")
    os.chmod(path, 0o600)
    return db


def initialize(path: Path | None = None, queue_path: Path | None = None) -> Path:
    path = path or admin_db_path(queue_path)
    with _connect(path) as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS security (
                id INTEGER PRIMARY KEY CHECK(id=1),
                pin_salt TEXT, pin_verifier TEXT,
                pin_version INTEGER NOT NULL DEFAULT 0,
                login_failures INTEGER NOT NULL DEFAULT 0,
                locked_until TEXT
            );
            CREATE TABLE IF NOT EXISTS security_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                occurred_at TEXT NOT NULL, action TEXT NOT NULL
            );
            INSERT OR IGNORE INTO security(id) VALUES(1);
        """)
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM security WHERE id=1").fetchone()
        if row["pin_version"] == 0 and queue_path is not None and queue_path.exists():
            from task_queue.db import open_queue_db
            with open_queue_db(queue_path) as queue:
                old = queue.execute("SELECT pin_salt,pin_verifier,pin_version,"
                                    "login_failures,locked_until FROM queue_security WHERE id=1").fetchone()
            if old and old["pin_version"] > 0 and old["pin_verifier"]:
                db.execute("UPDATE security SET pin_salt=?,pin_verifier=?,pin_version=?,"
                           "login_failures=?,locked_until=? WHERE id=1",
                           tuple(old))
                db.execute("INSERT INTO security_events(occurred_at,action) VALUES(?,?)",
                           (_now(), "queue_pin_migrated"))
    return path


def sync_legacy_queue(queue_path: Path) -> None:
    """Repair the Queue rollback verifier after a queue-only reset."""
    if not queue_path.exists():
        return
    path = initialize(queue_path=queue_path)
    from task_queue.db import open_queue_db
    with _connect(path) as db, open_queue_db(queue_path) as queue:
        current = db.execute("SELECT pin_salt,pin_verifier,pin_version FROM security WHERE id=1").fetchone()
        old = queue.execute("SELECT pin_version FROM queue_security WHERE id=1").fetchone()
        if current["pin_version"] > 0 and old and old["pin_version"] == 0:
            queue.execute("UPDATE queue_security SET pin_salt=?,pin_verifier=?,pin_version=? WHERE id=1",
                          tuple(current))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _verifier(pin: str, pepper: str, salt: bytes) -> str:
    return scrypt((pin + pepper).encode(), salt=salt, n=2**14, r=8, p=1).hex()


def pin_version(path: Path | None = None, queue_path: Path | None = None) -> int:
    path = initialize(path, queue_path)
    with _connect(path) as db:
        return int(db.execute("SELECT pin_version FROM security WHERE id=1").fetchone()[0])


def verify_pin(pin: str, pepper: str, path: Path | None = None,
               queue_path: Path | None = None, now: datetime | None = None) -> bool:
    path = initialize(path, queue_path)
    now = now or datetime.now(timezone.utc)
    with _connect(path) as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM security WHERE id=1").fetchone()
        if row["locked_until"] and now < datetime.fromisoformat(row["locked_until"]):
            return False
        if not row["pin_salt"] or not row["pin_verifier"]:
            return False
        valid = bool(isinstance(pin, str) and len(pin) == 6 and pin.isascii() and pin.isdigit()
                     and compare_digest(_verifier(pin, pepper, bytes.fromhex(row["pin_salt"])),
                                        row["pin_verifier"]))
        if valid:
            db.execute("UPDATE security SET login_failures=0,locked_until=NULL WHERE id=1")
            return True
        failures = row["login_failures"] + 1
        lock = (now + timedelta(minutes=15)).isoformat() if failures >= 5 else None
        db.execute("UPDATE security SET login_failures=?,locked_until=? WHERE id=1",
                   (0 if lock else failures, lock))
        db.execute("INSERT INTO security_events(occurred_at,action) VALUES(?,?)",
                   (_now(), "pin_login_locked" if lock else "pin_login_failed"))
        return False


def set_pin(pin: str, pepper: str, path: Path | None = None,
            queue_path: Path | None = None) -> None:
    if not isinstance(pin, str) or len(pin) != 6 or not pin.isascii() or not pin.isdigit():
        raise ValueError("PIN must be exactly six digits")
    if not isinstance(pepper, str) or len(pepper) < 32 or pepper.startswith("CHANGE_ME"):
        raise ValueError("QUEUE_WEB_PIN_PEPPER must have at least 32 characters")
    path = initialize(path, queue_path)
    salt = token_bytes(32)
    verifier = _verifier(pin, pepper, salt)
    with _connect(path) as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("UPDATE security SET pin_salt=?,pin_verifier=?,pin_version=pin_version+1,"
                   "login_failures=0,locked_until=NULL WHERE id=1",
                   (salt.hex(), verifier))
        version = db.execute("SELECT pin_version FROM security WHERE id=1").fetchone()[0]
        db.execute("INSERT INTO security_events(occurred_at,action) VALUES(?,?)",
                   (_now(), "pin_changed"))
    if queue_path is not None and queue_path.exists():
        # Keep the old verifier usable for rollback and clear temporary approvals.
        from task_queue.db import open_queue_db, transaction
        try:
            with open_queue_db(queue_path) as queue, transaction(queue):
                queue.execute("UPDATE queue_security SET pin_salt=?,pin_verifier=?,pin_version=?,"
                              "login_failures=0,locked_until=NULL,auto_approve_until=NULL,"
                              "auto_approve_session_id=NULL WHERE id=1",
                              (salt.hex(), verifier, version))
                queue.execute("INSERT INTO queue_security_events(occurred_at,action) VALUES(?,?)",
                              (_now(), "pin_changed"))
        except (OSError, sqlite3.Error, RuntimeError) as exc:
            # Shell auth stays available when the optional Queue store fails.
            logger.warning("Could not synchronize legacy Queue PIN state: %s", type(exc).__name__)
            with _connect(path) as db:
                db.execute("INSERT INTO security_events(occurred_at,action) VALUES(?,?)",
                           (_now(), "legacy_queue_pin_sync_failed"))


def main() -> None:
    pepper = os.environ.get("QUEUE_WEB_PIN_PEPPER", "")
    first = getpass("New six-digit Admin PIN: ")
    second = getpass("Repeat PIN: ")
    if first != second:
        raise SystemExit("PIN entries differ")
    queue_path = Path(os.environ.get("QUEUE_DB_PATH", "/home/ubuntu/queue.sqlite3"))
    set_pin(first, pepper, queue_path=queue_path)
    print("Admin PIN updated; previous sessions and queue auto-approval are invalid")


if __name__ == "__main__":
    main()
