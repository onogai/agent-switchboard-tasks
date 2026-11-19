# Switchboard Task Queue

Independent durable Task Queue add-on, with 14 FastMCP tools, SQLite, an hourly
scheduler, and a React management UI. This repository owns the Queue code and
images; **Gateway Core and Manager do not contain Queue Python packages**.

## Running modes

| Mode | Authentication | User interface |
| --- | --- | --- |
| Standalone | Queue's own PIN, session and CSRF | `/queue/` |
| Switchboard-managed | Private service bearer + Manager PIN/session; no Queue-local PIN | `/admin/queue/` served through Manager |

The managed Queue provides a private `/internal/queue/api/*` management API
and `/internal/queue/ui/*` assets. Manager authenticates the browser and
proxies both routes; the browser never receives `TASKS_ADMIN_TOKEN`.
Missing/invalid managed credentials fail closed, without standalone fallback.

The **managed production runtime** is one Python process and one container:
`python -m task_queue.runtime`. A single Uvicorn instance listens on ports
8767 (Manager Web/API) and 8771 (MCP), and runs one cancellable hourly
scheduler task. Existing `tasks_web` and `tasks_mcp` Docker DNS aliases
remain valid. The individual `mcp_server`, `tick` and `web` entrypoints
remain available for isolated staging/development, not production.

The image builds the standalone and managed React bundles from Queue-owned
`queue_ui/` source. No Gateway Registry or Telegram UI is bundled.

## Production

The production Queue now has its own [Compose manifest](compose.production.yaml)
and [deployment instructions](PRODUCTION.md). It retains the existing
`queue.sqlite3`, management token, internal DNS names and the single-scheduler
rule while consolidating three containers into one. The portable `compose.yaml` remains a separate staging/standalone
installation.

The running deployment is updated only after the host operator performs the
targeted `scripts/cutover_single_runtime.py` cutover. Merging this repository alone does not restart
production or migrate any state.

## Testing

`bash scripts/test.sh` builds a disposable Docker image and runs the Queue
unit/security tests without mounting live databases or secrets.
The CI workflow runs the same tests, including a disposable runtime smoke test for both ports, managed authentication, MCP handshake and scheduler. Managed browser-to-Manager integration is
also tested in the separately owned Core repository.

Preserve consistent SQLite/WAL backups; never run competing schedulers on
the same database, and never publish the MCP or managed Web ports to the
public Internet.
