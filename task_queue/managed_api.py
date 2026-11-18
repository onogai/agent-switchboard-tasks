"""Token-authenticated private Queue management routes for a Switchboard manager.

The standalone /queue API keeps its independent PIN and CSRF checks. Managed
routes are never exposed without an explicitly configured strong service token.
The manager checks its own browser session and CSRF before proxying requests.
"""

from __future__ import annotations

import re
from hmac import compare_digest

from starlette.routing import Route

from .web import BASE, reply


MANAGED_BASE = "/internal/queue/api"
_SESSION_ID = re.compile(r"[A-Za-z0-9_-]{20,128}\Z")


def routes_for_management(queue_routes: list[Route], token: str) -> list[Route]:
    """Reuse business handlers, not browser auth or a shared Gateway database."""
    result = []
    for route in queue_routes:
        if not isinstance(route, Route) or not route.path.startswith(BASE + "/api/"):
            continue
        suffix = route.path.removeprefix(BASE + "/api/")
        if suffix in {"session", "login", "logout"}:
            continue

        async def managed_handler(request, endpoint=route.endpoint):
            authorization = request.headers.get("authorization", "")
            if not compare_digest(authorization, "Bearer " + token):
                return reply({"error": "Managed service authentication required."}, 401)
            session_id = request.headers.get("x-switchboard-session-id", "")
            if not _SESSION_ID.fullmatch(session_id):
                return reply({"error": "Managed browser session required."}, 401)
            # Only the authenticated internal route is permitted to set this flag.
            request.scope["_managed_admin_session_id"] = session_id
            return await endpoint(request)

        result.append(Route(MANAGED_BASE + "/" + suffix, managed_handler,
                            methods=route.methods))
    return result
