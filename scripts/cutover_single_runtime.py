#!/usr/bin/env python3
"""One-time, rollback-safe migration from three Queue containers to one.

Builds before stopping anything, preserves the SQLite directory and secrets,
starts exactly one combined runtime, and verifies MCP/HTTP/DNS before retiring
the three stopped containers. Never runs Compose down or removes volumes.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".env.production"
COMPOSE = ROOT / "compose.production.yaml"
PROJECT = "switchboard-tasks"
NEW = "switchboard-tasks"
OLD = ("switchboard-tasks-tick", "switchboard-tasks-mcp", "switchboard-tasks-web")
ROLLBACK_IMAGE = "switchboard-tasks:rollback-before-single"


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=ROOT, text=True, capture_output=True)
    if check and result.returncode:
        raise RuntimeError("Command failed (details withheld): " + " ".join(args[:4]))
    return result


def docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run("docker", *args, check=check)


def compose(*args: str) -> None:
    docker("compose", "-p", PROJECT, "--env-file", str(ENV),
           "-f", str(COMPOSE), *args)


def inspect(name: str) -> dict:
    return json.loads(docker("inspect", name).stdout)[0]


def private_values() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in ENV.read_text().splitlines():
        if not line or line.lstrip().startswith("#"):
            continue
        if "=" not in line:
            raise RuntimeError("Malformed private Compose environment")
        key, value = line.split("=", 1)
        if key in values:
            raise RuntimeError("Duplicate environment setting: " + key)
        values[key] = value
    return values


def wait_healthy(seconds: int = 100) -> dict:
    for _ in range(seconds // 2):
        result = docker("inspect", NEW, check=False)
        if result.returncode == 0:
            current = json.loads(result.stdout)[0]
            status = current["State"]["Status"]
            health = current["State"].get("Health", {}).get("Status")
            if status == "running" and health == "healthy":
                return current
            if status in ("dead", "exited") or health == "unhealthy":
                raise RuntimeError("Unified Queue exited or became unhealthy")
        time.sleep(2)
    raise RuntimeError("Unified Queue healthcheck timed out")


def verify(state: Path, network: str, previous_image: str) -> None:
    new = wait_healthy()
    assert new["Config"]["Labels"]["com.docker.compose.project"] == PROJECT
    assert new["Config"]["Labels"]["com.docker.compose.service"] == "tasks"
    assert new["Image"] != previous_image, "New Queue image was not built"
    assert network in new["NetworkSettings"]["Networks"]
    aliases = new["NetworkSettings"]["Networks"][network].get("Aliases") or []
    assert "tasks_mcp" in aliases and "tasks_web" in aliases, "Legacy DNS aliases missing"
    mounts = [m for m in new["Mounts"] if m["Destination"] == "/data"]
    assert len(mounts) == 1 and Path(mounts[0]["Source"]).resolve() == state
    assert mounts[0]["RW"]
    assert new["HostConfig"]["PortBindings"] in (None, {}), "Unexpected host port"
    for name in OLD:
        assert not inspect(name)["State"]["Running"], "Old Queue process still running"

    # Check both old DNS names and ports from Core. The MCP GET status is
    # transport-dependent; the actual MCP handshake is checked below.
    docker("exec", "switchboard-prod-core", "python", "-c", """
import socket
import urllib.error
import urllib.request
for host, port in (('tasks_web', 8767), ('tasks_mcp', 8771)):
    with socket.create_connection((host, port), timeout=5):
        pass
try:
    urllib.request.urlopen(
        'http://tasks_web:8767/internal/queue/api/overview', timeout=5)
    raise AssertionError('Managed API was unauthenticated')
except urllib.error.HTTPError as error:
    assert error.code == 401, error.code
""")
    # MCP protocol handshake and catalog, not just an open TCP socket.
    docker("exec", NEW, "python", "-c", """
import asyncio
from fastmcp import Client
async def check():
    async with Client('http://127.0.0.1:8771/mcp') as client:
        tools = await client.list_tools()
        assert len(tools) == 14, [tool.name for tool in tools]
asyncio.run(check())
""")
    print("PASS: one healthy Queue, existing state, both DNS aliases, HTTP and 14 MCP tools",
          flush=True)


def main() -> None:
    if not ENV.is_file():
        raise RuntimeError("Missing private .env.production")
    values = private_values()
    state_text = values.get("TASKS_STATE_ROOT", "")
    if not state_text or not Path(state_text).is_absolute():
        raise RuntimeError("TASKS_STATE_ROOT must be an absolute path")
    state = Path(state_text).resolve()
    network = values.get("SWITCHBOARD_ADDONS_NETWORK") or "switchboard_addons"
    run("sudo", "-v")
    if run("sudo", "test", "-f", str(state / "queue.sqlite3"), check=False).returncode:
        raise RuntimeError("Queue database missing or inaccessible")
    if docker("inspect", NEW, check=False).returncode == 0:
        raise RuntimeError("Unified Queue container already exists; not repeating cutover")

    old = [inspect(name) for name in OLD]
    for name, info in zip(OLD, old):
        assert info["State"]["Running"], "Expected running old container: " + name
        assert info["Config"]["Labels"]["com.docker.compose.project"] == PROJECT
    previous_image = old[0]["Image"]
    assert all(info["Image"] == previous_image for info in old), "Old images differ"
    rollback_tag = docker("image", "inspect", ROLLBACK_IMAGE,
                          "--format", "{{.Id}}", check=False)
    if rollback_tag.returncode == 0 and rollback_tag.stdout.strip() != previous_image:
        raise RuntimeError("Existing rollback tag points to a different image")
    docker("tag", previous_image, ROLLBACK_IMAGE)
    compose("config", "--quiet")

    print("=== Build the new Queue image without downtime ===", flush=True)
    compose("build", "tasks")
    print("PASS: candidate image built; old services still running", flush=True)

    backup = Path.home() / "switchboard-cutover-backups" / (
        "tasks-single-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    stopped = False
    try:
        print("=== Stop old Queue processes and back up offline state ===", flush=True)
        # Mark the cutover active before the first stop: a partial stop
        # must also restart the original services on failure.
        stopped = True
        # Stop the scheduler first; no competing generation is ever allowed.
        for name in OLD:
            docker("stop", name)
        run("sudo", "install", "-d", "-m", "0700", str(backup))
        run("sudo", "tar", "-czf", str(backup / "state.tar.gz"), "-C", str(state), ".")
        run("sudo", "cp", "-a", str(ENV), str(backup / "env.production"))
        print("PASS: Queue state and private environment backed up", flush=True)

        print("=== Start and verify unified Queue ===", flush=True)
        compose("up", "-d", "--no-deps", "--no-build", "tasks")
        verify(state, network, previous_image)
    except BaseException:
        if stopped:
            print("ERROR: restoring original three Queue containers", file=sys.stderr,
                  flush=True)
            docker("rm", "-f", NEW, check=False)
            for name in ("switchboard-tasks-web", "switchboard-tasks-mcp",
                         "switchboard-tasks-tick"):
                if inspect(name)["State"]["Running"]:
                    continue
                result = docker("start", name, check=False)
                if result.returncode:
                    print("CRITICAL: failed to restart " + name, file=sys.stderr,
                          flush=True)
        raise

    for name in OLD:
        result = docker("rm", name, check=False)
        if result.returncode:
            print("WARN: stopped old container still exists: " + name, flush=True)
    print("PASS: Queue consolidation complete; one production container", flush=True)
    print("Private rollback backup:", backup, flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("FAILED:", error, file=sys.stderr)
        sys.exit(1)
