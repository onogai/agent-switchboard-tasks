# Switchboard Tasks

Independent durable Task Queue service: scheduler, MCP HTTP endpoint, PIN-protected Web UI and SQLite store. Extracted from agent-switchboard. **Do not deploy to production before full compatibility validation.**

MCP: `python -m task_queue.mcp_server` (port 8771). Scheduler: `python -m task_queue.tick`. Web: `uvicorn task_queue.web:create_app --factory --port 8767`.

Use a private Docker network for MCP and keep `QUEUE_DB_PATH`, `ADMIN_DB_PATH`, `QUEUE_WEB_PIN_PEPPER` and `QUEUE_WEB_SESSION_SECRET` consistent with the original state. Keep the original database backed up before cutover.
