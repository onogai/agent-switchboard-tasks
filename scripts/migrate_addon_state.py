"""Offline, conservative migration between production Queue and a staged add-on.

Never connects to Manager or mutates the Registry. Requires both Queue runtimes
stopped before copying an SQLite snapshot; legacy state remains intact.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
from uuid import uuid4

TABLES = (
    "task_definitions", "task_instances", "task_attempts",
    "task_events", "task_change_proposals",
)


class MigrationError(RuntimeError):
    pass


def read_env(path: Path) -> dict[str, str]:
    if not path.is_file() or path.is_symlink():
        raise MigrationError("Legacy .env.production must be a regular file")
    output = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:]
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip():
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            output[key.strip()] = value
    return output


def docker_json(*args: str):
    done = subprocess.run(
        ["docker", *args], text=True, capture_output=True, check=False
    )
    if done.returncode:
        raise MigrationError("Docker inspection failed; check Docker access")
    try:
        return json.loads(done.stdout)
    except ValueError as exc:
        raise MigrationError("Docker inspection returned invalid JSON") from exc


def assert_stopped_queue_containers(addon_root: Path, instance: str) -> None:
    legacy = docker_json("inspect", "switchboard-tasks")
    if len(legacy) != 1:
        raise MigrationError("Legacy Queue container not found")
    labels = legacy[0]["Config"].get("Labels") or {}
    if labels.get("com.docker.compose.project") != "switchboard-tasks":
        raise MigrationError("Legacy Queue container has an unexpected owner")
    if legacy[0]["State"]["Running"]:
        raise MigrationError("Stop legacy switchboard-tasks before migration")

    listed = subprocess.run(
        ["docker", "ps", "-aq", "--filter",
         "label=com.docker.compose.project=switchboard-addon-" + instance],
        text=True, capture_output=True, check=False,
    )
    if listed.returncode:
        raise MigrationError("Cannot inspect staged add-on containers")
    ids = listed.stdout.splitlines()
    if len(ids) != 1:
        raise MigrationError("Expected exactly one staged Queue container")
    candidate = docker_json("inspect", ids[0])[0]
    labels = candidate["Config"].get("Labels") or {}
    if (labels.get("com.docker.compose.project") != "switchboard-addon-" + instance
            or labels.get("com.docker.compose.service") != "queue"
            or labels.get("com.docker.compose.project.working_dir")
            != str((addon_root / "source").resolve())):
        raise MigrationError("Staged add-on container has unexpected ownership")
    if candidate["State"]["Running"]:
        raise MigrationError("Stop staged Queue container before migrating")


def snapshot(path: Path) -> dict:
    if not path.is_file() or path.is_symlink():
        raise MigrationError("Queue database missing or unsafe")
    uri = "file:" + str(path.resolve()) + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise MigrationError("Queue SQLite integrity_check failed")
        if db.execute("PRAGMA foreign_key_check").fetchall():
            raise MigrationError("Queue foreign key check failed")
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version != 2:
            raise MigrationError(f"Expected Queue schema v2, found v{version}")
        existing = {
            row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if not {"task_definitions", "task_instances"} <= existing:
            raise MigrationError("Not a recognized Queue database")
        counts = {
            table: db.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            for table in TABLES if table in existing
        }
    return {"version": version, "counts": counts}


def sqlite_backup(source: Path, destination: Path) -> None:
    if destination.exists() or destination.is_symlink():
        raise MigrationError("Refusing to overwrite a snapshot")
    uri = "file:" + str(source.resolve()) + "?mode=ro"
    src = sqlite3.connect(uri, uri=True)
    try:
        dest = sqlite3.connect(destination)
        try:
            src.backup(dest)
        finally:
            dest.close()
    finally:
        src.close()
    destination.chmod(0o600)
    snapshot(destination)


def private_write(path: Path, content: str) -> None:
    temporary = path.with_name(path.name + ".tmp." + uuid4().hex)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        with os.fdopen(os.open(temporary, flags, 0o600), "w") as stream:
            stream.write(content)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def migrate(legacy_env: Path, addon_root: Path, *,
            reverse: bool = False, commit: bool = False) -> dict:
    config = read_env(legacy_env)
    old_dir = Path(config.get("TASKS_STATE_ROOT", ""))
    if not old_dir.is_absolute() or old_dir.is_symlink():
        raise MigrationError("TASKS_STATE_ROOT must be an absolute, direct path")
    token = config.get("TASKS_ADMIN_TOKEN", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", token):
        raise MigrationError("Unsupported or invalid existing service token")
    info_path = addon_root / "installation.json"
    if not addon_root.is_absolute() or addon_root.is_symlink() or info_path.is_symlink() or not info_path.is_file():
        raise MigrationError("Missing or unsafe add-on metadata")
    info = json.loads(info_path.read_text())
    if (info.get("schema") != "2" or info.get("target") != "production"
            or info.get("addon_id") != "queue"
            or info.get("source_id") != info.get("instance")
            or info.get("service") != "queue"
            or info.get("services") != ["queue"]
            or not isinstance(info.get("staged_replacement"), dict) and not reverse):
        raise MigrationError("Queue add-on is not a verified staged production instance")
    instance = info["instance"]
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,29}", instance):
        raise MigrationError("Invalid Queue instance name")
    staged_dir = addon_root / "state" / "data"
    if not staged_dir.is_dir() or staged_dir.is_symlink():
        raise MigrationError("Missing add-on data directory")
    legacy_db = old_dir / "queue.sqlite3"
    staged_db = staged_dir / "queue.sqlite3"
    source = staged_db if reverse else legacy_db
    target = legacy_db if reverse else staged_db
    original = snapshot(source)
    if source.resolve() == target.resolve():
        raise MigrationError("Source and destination are the same database")
    if target.exists():
        snapshot(target)  # Never silently overwrite an unknown/corrupt database.
    generated_secret = addon_root / "state" / "secrets" / "admintoken"
    addon_config = addon_root / "config.env"
    if (generated_secret.is_symlink() or addon_config.is_symlink()
            or not generated_secret.is_file() or not addon_config.is_file()):
        raise MigrationError("Missing generated private add-on credentials")
    existing_lines = addon_config.read_text().splitlines()
    secret_lines = [line for line in existing_lines
                    if line.startswith("SWITCHBOARD_ADDON_SECRET_ADMINTOKEN=")]
    if len(secret_lines) != 1:
        raise MigrationError("Expected one generated Queue service token")

    summary = {"direction": "to-legacy" if reverse else "to-addon",
               "source": str(source), "destination": str(target),
               "schema": original["version"], "counts": original["counts"]}
    if not commit:
        return summary

    assert_stopped_queue_containers(addon_root, instance)
    os.umask(0o077)
    backups = addon_root / "migration-backups"
    if backups.is_symlink():
        raise MigrationError("Unsafe migration backup directory")
    backups.mkdir(mode=0o700, exist_ok=True)
    group = backups / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                       + "-" + uuid4().hex[:8])
    group.mkdir(mode=0o700)
    archived = group / "source.sqlite3"
    sqlite_backup(source, archived)

    # Save the full stopped target SQLite set before replacement; do not delete
    # WAL/SHM silently. The old production directory is never removed.
    target.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        candidate = target.with_name(target.name + suffix)
        if candidate.exists():
            if candidate.is_symlink() or not candidate.is_file():
                raise MigrationError("Unsafe existing destination database file")
            candidate.rename(group / ("previous-" + candidate.name))

    restored = target.with_name(target.name + ".migration-" + uuid4().hex)
    try:
        sqlite_backup(archived, restored)
        os.replace(restored, target)
    finally:
        restored.unlink(missing_ok=True)
    if snapshot(target) != original:
        raise MigrationError("Migrated Queue content differs from the source snapshot")

    if not reverse:
        # Preserve the production Manager's existing service-to-service token.
        private_write(group / "previous-admintoken", generated_secret.read_text())
        private_write(group / "previous-config.env", addon_config.read_text())
        private_write(generated_secret, token + "\n")
        changed = [
            "SWITCHBOARD_ADDON_SECRET_ADMINTOKEN=" + token
            if line.startswith("SWITCHBOARD_ADDON_SECRET_ADMINTOKEN=")
            else line
            for line in existing_lines
        ]
        private_write(addon_config, "\n".join(changed) + "\n")
    private_write(group / "summary.json", json.dumps(summary, indent=2) + "\n")
    return {**summary, "backup_dir": str(group)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy-env", type=Path, required=True)
    parser.add_argument("--addon-root", type=Path, required=True)
    parser.add_argument("--reverse", action="store_true",
                        help="Copy latest add-on DB back to the stopped legacy Queue")
    parser.add_argument("--commit", action="store_true")
    parser.add_argument("--confirm", help="Must equal add-on instance with --commit")
    args = parser.parse_args()
    root = args.addon_root.expanduser()
    if args.commit:
        expected = json.loads((root / "installation.json").read_text())["instance"]
        if args.confirm != expected:
            parser.error(f"--commit requires --confirm {expected}")
    result = migrate(args.legacy_env, root, reverse=args.reverse, commit=args.commit)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (MigrationError, OSError, sqlite3.Error, KeyError, ValueError) as exc:
        raise SystemExit(f"ERROR: {exc}")
