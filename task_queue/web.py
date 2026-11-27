"""LAN React application and JSON API for the durable task queue."""

from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
from secrets import compare_digest, token_urlsafe
from urllib.parse import urlsplit

from starlette.applications import Starlette
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .admin import (QueueAdminError, archive_definition, cancel_instance, create_definition,
                         get_definition, get_instance, list_definitions, list_instances,
                         retry_instance, trigger_definition, update_definition)
from .models import InstanceStatus
from .proposals import (auto_approval_state, decide_proposal, get_proposal,
                        list_proposals, set_auto_approval)
from .scheduler import parse
from .web_auth import pin_version, verify_pin

BASE = "/queue"
STATUSES = {status.value for status in InstanceStatus}


@dataclass(frozen=True)
class WebConfig:
    db_path: Path | None = None
    session_secret: str | None = None
    static_dir: Path = Path(__file__).parent.parent / "queue_ui" / "dist"
    managed_static_dir: Path = Path(__file__).parent.parent / "queue_ui" / "managed-dist"
    pin_pepper: str | None = None
    secure_cookie: bool = False
    managed_admin_token: str | None = None

    @classmethod
    def from_env(cls) -> WebConfig:
        path = os.environ.get("QUEUE_DB_PATH")
        return cls(Path(path) if path else None,
                   os.environ.get("QUEUE_WEB_SESSION_SECRET") or None,
                   pin_pepper=os.environ.get("QUEUE_WEB_PIN_PEPPER") or None,
                   secure_cookie=os.environ.get("QUEUE_WEB_SECURE_COOKIE") == "1",
                   managed_admin_token=os.environ.get("TASKS_ADMIN_TOKEN") or None)


def reply(data: object, status: int = 200) -> JSONResponse:
    return JSONResponse(data, status_code=status, headers={"Cache-Control": "no-store"})


def csrf_token(request: Request) -> str:
    if "csrf" not in request.session:
        request.session["csrf"] = token_urlsafe(32)
    return request.session["csrf"]


async def json_body(request: Request) -> dict:
    # Private managed requests already passed service-token authentication.
    # Browser requests must independently pass same-origin and CSRF checks.
    if not request.scope.get("_managed_admin_session_id"):
        origin = request.headers.get("origin")
        if origin and urlsplit(origin).netloc != request.url.netloc:
            raise QueueAdminError("Invalid request origin.")
        token = request.headers.get("x-csrf-token", "")
        if not token or not compare_digest(csrf_token(request), token):
            raise QueueAdminError("Invalid CSRF token. Reload the page and try again.")
    if request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
        raise QueueAdminError("Expected a JSON request.")
    raw = await request.body()
    if len(raw) > 150_000:
        raise QueueAdminError("Request is too large.")
    try:
        data = await request.json()
    except (ValueError, UnicodeDecodeError):
        raise QueueAdminError("Invalid JSON request.")
    if not isinstance(data, dict):
        raise QueueAdminError("Expected a JSON object.")
    return data


def integer(data: dict, key: str, default: int | None = None) -> int | None:
    raw = data.get(key)
    if raw is None or raw == "":
        return default
    if isinstance(raw, bool):
        raise QueueAdminError(f"{key} must be an integer.")
    try:
        value = int(raw)
    except (ValueError, TypeError):
        raise QueueAdminError(f"{key} must be an integer.")
    if str(value) != str(raw):
        raise QueueAdminError(f"{key} must be an integer.")
    return value


def optional(data: dict, key: str) -> str | None:
    value = data.get(key)
    return str(value).strip() or None if value is not None else None


def definition_values(data: dict) -> dict:
    if ("window_after_minutes" in data and "max_lateness_minutes" in data
            and data["window_after_minutes"] != data["max_lateness_minutes"]):
        raise QueueAdminError("Conflicting late-window values.")
    kind = data.get("schedule_kind", "manual")
    if kind == "one_shot":
        kind = "manual"
    if kind not in ("manual", "interval", "daily"):
        raise QueueAdminError("Unknown schedule kind.")
    return {
        **({"group": data["group"]} if "group" in data else {}),
        "title": str(data.get("title", "")),
        "instructions": str(data.get("instructions", "")),
        "schedule_kind": kind,
        "priority": integer(data, "priority", 5),
        "miss_policy": data.get("miss_policy", "run_late") if kind != "manual" or data.get("one_shot_at") else "run_late",
        "max_lateness_minutes": integer(data, "window_after_minutes",
                                         integer(data, "max_lateness_minutes", 30)),
        "window_before_minutes": integer(data, "window_before_minutes", 0),
        "one_shot_at": optional(data, "one_shot_at") if kind == "manual" else None,
        "lease_seconds": integer(data, "lease_seconds", 1800),
        "max_attempts": integer(data, "max_attempts", 3),
        "interval_minutes": integer(data, "interval_minutes") if kind == "interval" else None,
        "interval_anchor_at": optional(data, "interval_anchor_at") if kind == "interval" else None,
        "daily_time_local": optional(data, "daily_time_local") if kind == "daily" else None,
        "timezone_name": optional(data, "timezone_name") if kind == "daily" else None,
    }


async def mutation(request: Request, operation) -> Response:
    try:
        return reply(await operation(await json_body(request)))
    except (QueueAdminError, ValueError) as exc:
        status = 409 if "version conflict" in str(exc).lower() else 400
        return reply({"error": str(exc)}, status)


async def session(request: Request) -> Response:
    return reply({"csrf_token": csrf_token(request),
                  "authenticated": await authenticated(request)})


async def authenticated(request: Request) -> bool:
    if request.scope.get("_managed_admin_session_id"):
        return True
    version = request.session.get("pin_version")
    if not request.session.get("session_id") or not version:
        return False
    current = await asyncio.to_thread(pin_version, request.app.state.config.db_path)
    return version == current


def protected(handler):
    async def run(request: Request) -> Response:
        if not await authenticated(request):
            return reply({"error": "PIN login required."}, 401)
        return await handler(request)
    return run


async def login(request: Request) -> Response:
    try:
        data = await json_body(request)
        pin = data.get("pin", "")
        if not isinstance(pin, str):
            pin = ""
        config = request.app.state.config
        valid = await asyncio.to_thread(verify_pin, pin, config.pin_pepper,
                                        config.db_path)
        if not valid:
            return reply({"error": "Invalid PIN or temporarily locked."}, 401)
        request.session.clear()
        request.session["session_id"] = token_urlsafe(24)
        request.session["pin_version"] = await asyncio.to_thread(pin_version,
                                                                 config.db_path)
        return reply({"authenticated": True, "csrf_token": csrf_token(request)})
    except QueueAdminError as exc:
        return reply({"error": str(exc)}, 400)


async def logout(request: Request) -> Response:
    try:
        await json_body(request)
        request.session.clear()
        return reply({"authenticated": False})
    except QueueAdminError as exc:
        return reply({"error": str(exc)}, 400)


async def overview(request: Request) -> Response:
    path = request.app.state.config.db_path
    now = datetime.now(timezone.utc)
    instances = await asyncio.to_thread(list_instances, path, None, now)
    definitions = await asyncio.to_thread(list_definitions, path)
    active = {row["id"]: row for row in definitions
              if row["is_active"] and row["archived_at"] is None}
    claimable = [row for row in instances
                 if row["status"] == "ready" and parse(row["ready_at"]) <= now
                 and row["definition_id"] in active
                 and row["attempt_count"] < row["max_attempts_snapshot"]
                 and (row["miss_policy_snapshot"] == "run_late"
                      or row["window_end_at"] >= now.isoformat())]
    upcoming = sorted((row for row in instances if row["status"] == "future"
                       and row["definition_id"] in active),
                      key=lambda row: (row["scheduled_at"], row["id"]))
    recent = sorted((row for row in instances if row["status"] in
                     ("succeeded", "failed", "skipped", "merged", "cancelled")),
                    key=lambda row: row["updated_at"], reverse=True)
    return reply({
        "now": now.isoformat(), "counts": dict(Counter(row["status"] for row in instances)),
        "claimable_count": len(claimable), "active_rule_count": len(active),
        "rule_count": len(definitions),
        "next_due_at": upcoming[0]["scheduled_at"] if upcoming else None,
        "claimable": sorted(claimable, key=lambda row:
                            (-row["priority_snapshot"], row["ready_at"]))[:10],
        "upcoming": upcoming[:10], "recent": recent[:10],
    })


async def definitions(request: Request) -> Response:
    return reply({"definitions": await asyncio.to_thread(
        list_definitions, request.app.state.config.db_path)})


async def definition(request: Request) -> Response:
    try:
        return reply(await asyncio.to_thread(get_definition,
                     request.path_params["definition_id"], request.app.state.config.db_path))
    except QueueAdminError:
        return reply({"error": "Rule not found."}, 404)


async def instances(request: Request) -> Response:
    status = request.query_params.get("status") or None
    if status is not None and status not in STATUSES:
        return reply({"error": "Unknown task status."}, 400)
    return reply({"instances": await asyncio.to_thread(
        list_instances, request.app.state.config.db_path, status)})


async def instance(request: Request) -> Response:
    try:
        return reply(await asyncio.to_thread(get_instance,
                     request.path_params["instance_id"], request.app.state.config.db_path))
    except QueueAdminError:
        return reply({"error": "Task not found."}, 404)


async def create_rule(request: Request) -> Response:
    async def run(data):
        identifier = await asyncio.to_thread(create_definition,
            **definition_values(data), db_path=request.app.state.config.db_path)
        return {"id": identifier}
    return await mutation(request, run)


async def update_rule(request: Request) -> Response:
    async def run(data):
        identifier = request.path_params["definition_id"]
        expected = integer(data, "expected_version")
        if expected is None:
            raise QueueAdminError("expected_version is required.")
        await asyncio.to_thread(update_definition, identifier, definition_values(data),
                                request.app.state.config.db_path, None, expected)
        return {"id": identifier}
    return await mutation(request, run)


async def toggle_rule(request: Request) -> Response:
    async def run(data):
        identifier = request.path_params["definition_id"]
        active = data.get("is_active")
        expected = integer(data, "expected_version")
        if type(active) is not bool or expected is None:
            raise QueueAdminError("is_active and expected_version are required.")
        await asyncio.to_thread(update_definition, identifier, {"is_active": active},
                                request.app.state.config.db_path, None, expected)
        return {"id": identifier, "is_active": active}
    return await mutation(request, run)


async def trigger_rule(request: Request) -> Response:
    async def run(_data):
        identifier = await asyncio.to_thread(trigger_definition,
            request.path_params["definition_id"], request.app.state.config.db_path)
        return {"id": identifier}
    return await mutation(request, run)


async def cancel_task(request: Request) -> Response:
    async def run(_data):
        identifier = request.path_params["instance_id"]
        await asyncio.to_thread(cancel_instance, identifier, request.app.state.config.db_path)
        return {"id": identifier}
    return await mutation(request, run)


async def retry_task(request: Request) -> Response:
    async def run(_data):
        identifier = await asyncio.to_thread(retry_instance,
            request.path_params["instance_id"], request.app.state.config.db_path)
        return {"id": identifier}
    return await mutation(request, run)


async def archive_rule(request: Request) -> Response:
    async def run(data):
        identifier = request.path_params["definition_id"]
        expected = integer(data, "expected_version")
        if expected is None:
            raise QueueAdminError("expected_version is required.")
        await asyncio.to_thread(archive_definition, identifier,
                                request.app.state.config.db_path, None, expected)
        return {"id": identifier}
    return await mutation(request, run)


async def proposals(request: Request) -> Response:
    try:
        limit = int(request.query_params.get("limit", "50"))
        offset = int(request.query_params.get("offset", "0"))
        rows = await asyncio.to_thread(list_proposals, request.app.state.config.db_path,
                                       request.query_params.get("status"), limit, offset)
        return reply({"proposals": rows})
    except (ValueError, QueueAdminError) as exc:
        return reply({"error": str(exc)}, 400)


async def proposal(request: Request) -> Response:
    try:
        return reply(await asyncio.to_thread(get_proposal,
                     request.path_params["proposal_id"], request.app.state.config.db_path))
    except QueueAdminError:
        return reply({"error": "Proposal not found."}, 404)


def admin_session_id(request: Request) -> str:
    """Keep per-browser approval binding in both auth modes."""
    return request.scope.get("_managed_admin_session_id") or request.session["session_id"]


async def proposal_decision(request: Request) -> Response:
    async def run(_data):
        return await asyncio.to_thread(
            decide_proposal, request.path_params["proposal_id"],
            request.url.path.endswith("/approve"), admin_session_id(request),
            request.app.state.config.db_path,
        )
    return await mutation(request, run)


async def auto_approval(request: Request) -> Response:
    if request.method == "GET":
        return reply(await asyncio.to_thread(auto_approval_state,
                                             request.app.state.config.db_path))
    async def run(data):
        session_id = admin_session_id(request)
        if request.scope.get("_managed_admin_session_id"):
            from .managed_approval import managed_session
            version = request.scope.get("_managed_admin_pin_version")
            if type(version) is not int or version < 1:
                raise QueueAdminError("Central Manager PIN epoch is required.")
            session_id = managed_session(session_id, version)
        return await asyncio.to_thread(set_auto_approval, data.get("enabled"),
                                       session_id,
                                       request.app.state.config.db_path)
    return await mutation(request, run)


async def spa(request: Request) -> Response:
    if request.url.path.startswith(f"{BASE}/api/"):
        return reply({"error": "API route not found."}, 404)
    index = request.app.state.config.static_dir / "index.html"
    if not index.is_file():
        return Response("Queue UI build is missing.", status_code=503)
    return FileResponse(index, media_type="text/html", headers={"Cache-Control": "no-store"})


def create_app(config: WebConfig | None = None) -> Starlette:
    config = config or WebConfig.from_env()
    if config.managed_admin_token:
        if (len(config.managed_admin_token) < 32 or
                config.managed_admin_token.startswith("CHANGE_ME")):
            raise RuntimeError("TASKS_ADMIN_TOKEN must be a strong service secret.")
    elif (not config.session_secret or len(config.session_secret) < 32
          or config.session_secret.startswith("CHANGE_ME")
          or not config.pin_pepper or len(config.pin_pepper) < 32
          or config.pin_pepper.startswith("CHANGE_ME")):
        raise RuntimeError("Standalone Queue PIN secret and pepper are required.")
    routes = [
        Route(BASE, lambda _: RedirectResponse(f"{BASE}/", status_code=307)),
        Route(f"{BASE}/api/session", session),
        Route(f"{BASE}/api/login", login, methods=["POST"]),
        Route(f"{BASE}/api/logout", protected(logout), methods=["POST"]),
        Route(f"{BASE}/api/overview", protected(overview)),
        Route(f"{BASE}/api/definitions", protected(definitions), methods=["GET"]),
        Route(f"{BASE}/api/definitions", protected(create_rule), methods=["POST"]),
        Route(f"{BASE}/api/definitions/{{definition_id}}", protected(definition), methods=["GET"]),
        Route(f"{BASE}/api/definitions/{{definition_id}}", protected(update_rule), methods=["PUT"]),
        Route(f"{BASE}/api/definitions/{{definition_id}}/toggle", protected(toggle_rule), methods=["POST"]),
        Route(f"{BASE}/api/definitions/{{definition_id}}/trigger", protected(trigger_rule), methods=["POST"]),
        Route(f"{BASE}/api/definitions/{{definition_id}}/archive", protected(archive_rule), methods=["POST"]),
        Route(f"{BASE}/api/instances", protected(instances)),
        Route(f"{BASE}/api/instances/{{instance_id}}", protected(instance)),
        Route(f"{BASE}/api/instances/{{instance_id}}/cancel", protected(cancel_task), methods=["POST"]),
        Route(f"{BASE}/api/instances/{{instance_id}}/retry", protected(retry_task), methods=["POST"]),
        Route(f"{BASE}/api/proposals", protected(proposals)),
        Route(f"{BASE}/api/proposals/{{proposal_id}}", protected(proposal)),
        Route(f"{BASE}/api/proposals/{{proposal_id}}/approve", protected(proposal_decision), methods=["POST"]),
        Route(f"{BASE}/api/proposals/{{proposal_id}}/reject", protected(proposal_decision), methods=["POST"]),
        Route(f"{BASE}/api/auto-approval", protected(auto_approval), methods=["GET", "POST"]),
    ]
    if config.managed_admin_token:
        # Managed is exclusive: no browser PIN endpoints and no automatic
        # fallback if the Switchboard token is missing or incorrect.
        from .managed_api import routes_for_management
        app = Starlette(routes=routes_for_management(
            routes, config.managed_admin_token, config.managed_static_dir))
        app.state.config = config
        return app
    assets = config.static_dir / "assets"
    if assets.is_dir():
        routes.append(Mount(f"{BASE}/assets", app=StaticFiles(directory=assets), name="assets"))
    routes.append(Route(f"{BASE}/{{path:path}}", spa))
    app = Starlette(routes=routes)
    app.state.config = config
    app.add_middleware(SessionMiddleware, secret_key=config.session_secret,
                       session_cookie="queue_session", same_site="lax", max_age=43200,
                       https_only=config.secure_cookie, path=BASE)
    return app
