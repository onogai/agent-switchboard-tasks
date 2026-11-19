"""One managed Queue process: HTTP MCP, Manager API/UI, and scheduler.

A single Uvicorn server listens on both historical internal ports so the
Gateway Registry and Manager do not need endpoint migrations. Both sockets
serve the same ASGI application; routes retain their existing authentication.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
import logging
import socket

from starlette.applications import Starlette
from starlette.routing import Mount
import uvicorn

from .mcp_server import mcp
from .scheduler import generate_future
from .tick import seconds_until_next_hour
from .web import WebConfig, create_app


LOG = logging.getLogger(__name__)
WEB_PORT = 8767
MCP_PORT = 8771


async def schedule_forever() -> None:
    """Preserve the old hourly tick cadence with one cancellable task."""
    while True:
        try:
            await asyncio.to_thread(generate_future)
            LOG.info("Queue generation completed")
        except Exception:
            LOG.exception("Queue generation failed; retrying in one minute")
            await asyncio.sleep(60)
            continue
        await asyncio.sleep(seconds_until_next_hour(datetime.now(timezone.utc)))


def create_runtime_app() -> Starlette:
    config = WebConfig.from_env()
    if not config.managed_admin_token:
        raise RuntimeError("Single-container production runtime requires TASKS_ADMIN_TOKEN")
    web_app = create_app(config)
    mcp_app = mcp.http_app(path="/mcp")

    @asynccontextmanager
    async def lifespan(app: Starlette):
        # FastMCP requires its session-manager lifespan to be driven by the
        # outer ASGI app. Mounted apps do not receive lifespan automatically.
        async with mcp_app.lifespan(app):
            scheduler = asyncio.create_task(schedule_forever(), name="queue-scheduler")
            try:
                yield
            finally:
                scheduler.cancel()
                with suppress(asyncio.CancelledError):
                    await scheduler

    # Web routes match only /internal/queue/... in managed mode. The final
    # root mount delegates /mcp to the complete FastMCP ASGI application,
    # including its own middleware.
    app = Starlette(routes=[*web_app.routes, Mount("/", app=mcp_app)],
                    lifespan=lifespan)
    app.state.config = config
    return app


def bind(port: int) -> socket.socket:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("0.0.0.0", port))
        listener.listen(2048)
        return listener
    except BaseException:
        listener.close()
        raise


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    app = create_runtime_app()
    sockets: list[socket.socket] = []
    try:
        sockets = [bind(WEB_PORT)]
        sockets.append(bind(MCP_PORT))
        uvicorn.Server(uvicorn.Config(app, log_level="info")).run(sockets=sockets)
    finally:
        for listener in sockets:
            listener.close()


if __name__ == "__main__":
    main()
