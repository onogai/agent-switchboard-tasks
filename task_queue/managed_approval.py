"""Managed auto-approval authority, independent of the Switchboard codebase.

A Queue worker must validate the Manager's current PIN epoch immediately before
automatically approving a proposed task change. An offline or misconfigured
Manager means the proposal stays pending; standalone PIN behavior is unchanged.
"""

from __future__ import annotations

import os
import re

import httpx

_MANAGED_SESSION = re.compile(r"managed:v([1-9][0-9]{0,12}):([A-Za-z0-9_-]{20,128})\Z")


def managed_session(session_id: str, version: int) -> str:
    if not session_id or not isinstance(version, int) or version < 1:
        raise ValueError("Managed session and positive PIN version are required")
    token = f"managed:v{version}:{session_id}"
    if not _MANAGED_SESSION.fullmatch(token):
        raise ValueError("Invalid managed session binding")
    return token


def is_managed_session(session_id: str | None) -> bool:
    return bool(session_id and session_id.startswith("managed:"))


def authority_valid(version: int) -> bool:
    """Fail closed. Never take the local/standalone PIN path on auth failure."""
    url = os.environ.get("TASKS_AUTHORITY_URL", "")
    token = os.environ.get("TASKS_ADMIN_TOKEN", "")
    if (not url or not url.startswith(("http://", "https://")) or
            not token or len(token) < 32 or token.startswith("CHANGE_ME")):
        return False
    try:
        response = httpx.post(
            url.rstrip("/") + "/admin/internal/queue/validate-pin-version",
            headers={"Authorization": "Bearer " + token},
            json={"pin_version": version},
            timeout=2.0,
            follow_redirects=False,
        )
        return response.status_code == 200 and response.json() == {"valid": True}
    except (httpx.HTTPError, ValueError):
        return False


def auto_approval_authorized(session_id: str | None) -> bool:
    """Enforce central epoch for managed approvals even in MCP worker processes."""
    if not session_id:
        return False
    match = _MANAGED_SESSION.fullmatch(session_id)
    if match:
        return authority_valid(int(match.group(1)))
    if is_managed_session(session_id):
        return False
    # If workers are deployed as managed, never honor leftover standalone leases.
    return not bool(os.environ.get("TASKS_ADMIN_TOKEN"))
