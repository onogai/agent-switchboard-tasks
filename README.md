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

The shared Queue application has three entrypoints:

- MCP: `python -m task_queue.mcp_server` (HTTP port 8771)
- Scheduler: `python -m task_queue.tick` (exactly one active instance per DB)
- Web/API: `uvicorn task_queue.web:create_app --factory --port 8767`

The image builds the standalone and managed React bundles from Queue-owned
`queue_ui/` source. No Gateway Registry or Telegram UI is bundled.

## Production

The modular production cutover completed on **18 November 2026**.
Gateway Core and Manager are deployed from `onogai/agent-switchboard`;
Task Queue uses its own image and SQLite state, presently under
`/home/onogai/agent-switchboard-tasks/state/queue.sqlite3`.
The Core repository owns production orchestration; **do not run this
repository's standalone Compose against that production project**.

The production-compatible Queue source comes from the consolidated M7–M9
managed architecture in this repository. Existing deployments must retain
their current state directory, service token, PIN epoch authority, registry
contracts/grants and image references. A Git merge does **not** trigger a
container rebuild, SQLite migration or scheduler restart.

See [INSTALL.md](INSTALL.md) for setup and deployment boundaries, and
[MANAGED_AUTH.md](MANAGED_AUTH.md) for the managed security contract.

## Testing

`bash scripts/test.sh` builds a disposable Docker image and runs the Queue
unit/security tests without mounting live databases or secrets.
The CI workflow runs the same test. Managed browser-to-Manager integration is
also tested in the separately owned Core repository.

Preserve consistent SQLite/WAL backups; never run competing schedulers on
the same database, and never publish the MCP or managed Web ports to the
public Internet.
