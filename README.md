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

## M9: frontend ownership

Task Queue owns its own React application in `queue_ui/`. Its image now
contains two independently compiled bundles from that source:

- `/queue/` — standalone web UI, local PIN authentication.
- `/admin/queue/` — Manager-hosted UI, same central Switchboard session,
  Queue JSON requests via `/admin/api/queue/*`.

In managed mode, only the private service-token-protected
`/internal/queue/ui/*` asset endpoint is served. Switchboard Manager proxies
its HTML/JS under `/admin/queue/*` after validating the browser's central
PIN session. The Queue service never receives the central PIN and the browser
never sees `TASKS_ADMIN_TOKEN`. No Gateway/Telegram React code is bundled in
Task Queue's frontend.

Run `bash scripts/test.sh` for standalone and managed smoke tests. Use the
matching Manager M9 integration gate to verify browser asset delivery across
separate Docker images.
