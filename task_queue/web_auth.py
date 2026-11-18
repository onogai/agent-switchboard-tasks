"""Compatibility entry points for the Infrastructure Admin PIN.

Queue web and the PIN CLI now use the shell-owned verifier. Queue task data and
temporary auto-approval remain in the queue database.
"""

from __future__ import annotations

import os
from datetime import datetime
from getpass import getpass
from pathlib import Path

from . import auth

from .db import open_queue_db, queue_db_path


def _queue_path(path: Path | None) -> Path:
    return path or queue_db_path()


def set_pin(pin: str, pepper: str, db_path: Path | None = None) -> None:
    path = _queue_path(db_path)
    with open_queue_db(path):
        pass
    auth.set_pin(pin, pepper, queue_path=path)


def pin_version(db_path: Path | None = None) -> int:
    path = _queue_path(db_path)
    auth.sync_legacy_queue(path)
    return auth.pin_version(queue_path=path)


def verify_pin(pin: str, pepper: str, db_path: Path | None = None,
               now: datetime | None = None) -> bool:
    path = _queue_path(db_path)
    auth.sync_legacy_queue(path)
    return auth.verify_pin(pin, pepper, queue_path=path, now=now)


def main() -> None:
    pepper = os.environ.get("QUEUE_WEB_PIN_PEPPER", "")
    first = getpass("New six-digit Admin PIN: ")
    second = getpass("Repeat PIN: ")
    if first != second:
        raise SystemExit("PIN entries differ")
    set_pin(first, pepper)
    print("Admin PIN updated; previous sessions and queue auto-approval are invalid")


if __name__ == "__main__":
    main()
