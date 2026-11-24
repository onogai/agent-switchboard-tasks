"""TEST-ONLY failure injection for Switchboard's safe-state update acceptance.

Only the isolated instance 'queuestatecheck' may modify its own SQLite.
A v3 marker is committed, then two dummy HTTP listeners satisfy Docker's
TCP healthcheck but deliberately refuse MCP calls. This forces a failure
in the *authenticated/catalog acceptance phase*, after the candidate has
become healthy, without starting a scheduler or making external calls.

Never merge this test module or Compose command into the release branch.
"""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import sqlite3
import sys
import threading


class RefuseMcp(BaseHTTPRequestHandler):
    def _reject(self) -> None:
        self.send_response(503)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"TEST ONLY: deliberately unavailable MCP")

    def do_POST(self) -> None:
        self._reject()

    def do_GET(self) -> None:
        self._reject()

    def log_message(self, fmt: str, *args: object) -> None:
        return


def main() -> int:
    if os.environ.get("LIFECYCLE_PROBE_INSTANCE") != "queuestatecheck":
        print("LIFECYCLE_PROBE: unexpected instance; refusing database change",
              file=sys.stderr, flush=True)
        return 64
    db_path = os.environ.get("QUEUE_DB_PATH")
    if db_path != "/data/queue.sqlite3" or not Path(db_path).is_file():
        print("LIFECYCLE_PROBE: missing expected Queue database",
              file=sys.stderr, flush=True)
        return 65

    with sqlite3.connect(db_path, timeout=15) as conn:
        current = conn.execute("PRAGMA user_version").fetchone()[0]
        if current not in (2, 3):
            print("LIFECYCLE_PROBE: unexpected schema version; no changes",
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

    servers = [
        ThreadingHTTPServer(("0.0.0.0", port), RefuseMcp)
        for port in (8767, 8771)
    ]
    for server in servers[1:]:
        threading.Thread(target=server.serve_forever, daemon=True).start()
    print("LIFECYCLE_PROBE: SQLite v3 marker committed; Docker health passes, "
          "MCP intentionally returns 503 (no scheduler started)",
          file=sys.stderr, flush=True)
    try:
        servers[0].serve_forever()
    finally:
        for server in servers:
            server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
