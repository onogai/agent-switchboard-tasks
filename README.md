# Switchboard Tasks

Independent durable Task Queue service: scheduler, MCP HTTP endpoint and SQLite
store. It works alone **or** as an optional Switchboard add-on.

- **Standalone** (no `TASKS_ADMIN_TOKEN`): local PIN-protected `/queue` Web UI.
  Configure `QUEUE_WEB_PIN_PEPPER` and `QUEUE_WEB_SESSION_SECRET`.
- **Managed** (strong `TASKS_ADMIN_TOKEN` configured): private
  `/internal/queue/api/*` management endpoints only. Switchboard Admin owns
  the browser login, PIN, session and CSRF checks. No local PIN, cookie
  or shared Gateway database is needed. Invalid manager credentials **never**
  fall back to a standalone PIN.

MCP: `python -m task_queue.mcp_server` (port 8771).
Scheduler: `python -m task_queue.tick`.
Web: `uvicorn task_queue.web:create_app --factory --port 8767`.

Run `bash scripts/test.sh` for disposable Docker verification. Keep the Queue
SQLite state backed up, only run one scheduler against a given database, and
never expose the MCP or managed Web ports publicly.

**Staging only:** do not deploy production cutover before M7 compatibility tests.
