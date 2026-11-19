#!/usr/bin/env bash
# Exercise the actual unified process with disposable state and no network access.
set -Eeuo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
name="switchboard-tasks-runtime-smoke-$$"
cleanup() { docker rm -f "$name" >/dev/null 2>&1 || true; }
trap cleanup EXIT

docker run -d --name "$name" --network none \
  -e TASKS_ADMIN_TOKEN=0123456789abcdef0123456789abcdef0123456789abcdef \
  -e QUEUE_DB_PATH=/tmp/queue.sqlite3 \
  --entrypoint python switchboard-tasks-test:local \
  -m task_queue.runtime >/dev/null

ready=0
for attempt in $(seq 1 40); do
  if docker exec "$name" python -c '
import socket
for port in (8767, 8771):
    with socket.create_connection(("127.0.0.1", port), timeout=1):
        pass
' >/dev/null 2>&1; then
    ready=1
    break
  fi
  if [[ "$(docker inspect -f '{{.State.Running}}' "$name")" != true ]]; then
    docker logs "$name"
    exit 1
  fi
  sleep 1
done
if [[ "$ready" != 1 ]]; then
  docker logs "$name"
  echo "Unified Queue failed to listen on both ports" >&2
  exit 1
fi

docker exec "$name" python -c '
import asyncio
from pathlib import Path
import sqlite3
from urllib.error import HTTPError
from urllib.request import urlopen
from fastmcp import Client

try:
    urlopen("http://127.0.0.1:8767/internal/queue/api/overview", timeout=3)
    raise AssertionError("Managed Queue endpoint was unauthenticated")
except HTTPError as exc:
    assert exc.code == 401, exc.code

async def check_mcp():
    async with Client("http://127.0.0.1:8771/mcp") as client:
        tools = await client.list_tools()
        assert len(tools) == 14, [tool.name for tool in tools]

asyncio.run(check_mcp())
db = Path("/tmp/queue.sqlite3")
assert db.is_file(), "Scheduler did not initialize its SQLite state"
with sqlite3.connect(db) as connection:
    assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
print("PASS: unified Queue MCP, managed Web auth and scheduler")
'
