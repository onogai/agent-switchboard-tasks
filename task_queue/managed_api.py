"""Token-authenticated private Queue management routes for a Switchboard manager.

The standalone /queue API keeps its independent PIN and CSRF checks. Managed
routes are never exposed without an explicitly configured strong service token.
The manager checks its own browser session and CSRF before proxying requests.
"""

from __future__ import annotations

import re
from pathlib import Path

from starlette.responses import FileResponse
from hmac import compare_digest

from starlette.routing import Route

from .web import BASE, reply


MANAGED_BASE = "/internal/queue/api"
_SESSION_ID = re.compile(r"[A-Za-z0-9_-]{20,128}\Z")


def routes_for_management(queue_routes: list[Route], token: str, static_dir: Path) -> list[Route]:
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
            epoch = request.headers.get("x-switchboard-pin-version", "")
            if epoch and epoch.isascii() and epoch.isdecimal() and len(epoch) <= 12:
                version = int(epoch)
                if version > 0:
                    request.scope["_managed_admin_pin_version"] = version
            return await endpoint(request)

        result.append(Route(MANAGED_BASE + "/" + suffix, managed_handler,
                            methods=route.methods))
    async def managed_ui(request):
        # Queue UI is an add-on-owned asset, served only to the Manager proxy.
        # The browser never receives the private service token.
        authorization = request.headers.get("authorization", "")
        session_id = request.headers.get("x-switchboard-session-id", "")
        if not compare_digest(authorization, "Bearer " + token) or not _SESSION_ID.fullmatch(session_id):
            return reply({"error": "Manager authentication required."}, 401)
        tail = request.path_params.get("tail", "")
        if tail.startswith("assets/"):
            filename = tail.removeprefix("assets/")
            if not re.fullmatch(r"[A-Za-z0-9._-]{1,200}", filename) or filename.startswith("."):
                return reply({"error": "Asset not found."}, 404)
            path = static_dir / "assets" / filename
            if not path.is_file():
                return reply({"error": "Asset not found."}, 404)
            return FileResponse(path, headers={"Cache-Control": "public, max-age=3600"})
        # SPA fallback only for reasonable routes: never serve hidden or path traversal files.
        if tail and (not re.fullmatch(r"[A-Za-z0-9_./-]{1,512}", tail) or
                     any(p in {".", "..", ""} for p in tail.split("/"))):
            return reply({"error": "UI route not found."}, 404)
        index = static_dir / "index.html"
        if not index.is_file():
            return reply({"error": "Queue UI build missing."}, 503)
        return FileResponse(index, media_type="text/html",
                            headers={"Cache-Control": "no-store"})

    result.append(Route("/internal/queue/ui", managed_ui, methods=["GET"]))
    result.append(Route("/internal/queue/ui/{tail:path}", managed_ui, methods=["GET"]))
    return result
