"""TEST-ONLY failure injection for Switchboard's safe-state update acceptance.

Only the isolated instance 'queuestatecheck' is allowed to touch its own
Queue SQLite database. This module is never imported by the release runtime.
It creates no tasks, sends nothing, and deliberately fails after committing
a reversible schema-version change, so the host updater must fail closed.
"""
from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import sys


def main() -> int:
    if os.environ.get("LIFECYCLE_PROBE_INSTANCE") != "queuestatecheck":
        print("LIFECYCLE_PROBE: wrong instance; refusing any database changes",
              file=sys.stderr, flush=True)
        return 64
    db_path = os.environ.get("QUEUE_DB_PATH")
    if db_path != "/data/queue.sqlite3" or not Path(db_path).is_file():
        print("LIFECYCLE_PROBE: missing expected existing test Queue DB",
              file=sys.stderr, flush=True)
        return 65

    with sqlite3.connect(db_path, timeout=15) as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version not in (2, 3):
            print("LIFECYCLE_PROBE: unexpected schema version; refusing mutation",
                  file=sys.stderr, flush=True)
            return 66
        conn.execute(
            "CREATE TABLE IF NOT EXISTS lifecycle_state_probe "
            "(id INTEGER PRIMARY KEY, marker TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT OR IGNORE INTO lifecycle_state_probe(id, marker) "
            "VALUES(1, 'candidate-v3-failure')"
        )
        conn.execute("PRAGMA user_version = 3")
        conn.commit()

    print("LIFECYCLE_PROBE: committed reversible v3 marker; exiting 73 deliberately",
          file=sys.stderr, flush=True)
    return 73


if __name__ == "__main__":
    raise SystemExit(main())
