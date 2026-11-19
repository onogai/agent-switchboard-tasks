# Switchboard Task Queue

Independent durable Task Queue with 14 FastMCP tools, SQLite, hourly
scheduling, and a React management UI. Gateway Core/Manager do not include
Queue Python packages.

## One container in both running modes

Both Compose manifests start `python -m task_queue.runtime`: one process
serving HTTP MCP at port 8771, Web/API at port 8767, and exactly one
in-process scheduler.

| Mode | Config | Auth and UI |
| --- | --- | --- |
| Managed production | `compose.production.yaml` | Manager PIN/session plus private service bearer; UI via Manager at `/admin/queue/` |
| Disposable standalone | `compose.yaml` | Queue's own PIN/session/CSRF; UI at `/queue/` |

Managed API/UI is available only at `/internal/queue/*`, requiring
`TASKS_ADMIN_TOKEN`; it never falls back to the standalone PIN routes.
The browser never receives the service token. Standalone instead requires
`QUEUE_WEB_SESSION_SECRET` and `QUEUE_WEB_PIN_PEPPER`.

MCP and Web ports retain the internal Docker aliases `tasks_mcp` and
`tasks_web`, so Gateway/Manager do not need endpoint changes. Only
standalone Web is optionally published to `127.0.0.1:18769`.
The MCP port is private in both modes.

The image builds both standalone and managed UI bundles from `queue_ui/`.
The separate module entrypoints `mcp_server`, `tick`, and `web` remain
available for tests; do not start them alongside the unified runtime on
the same production database.

## Fresh Git-based managed installation

Install directly from this repo (or a fork with the same v1 manifest)
using the host-side Switchboard installer:

```bash
./switchboard addon https://github.com/onogai/agent-switchboard-tasks.git
```

`switchboard-addon.yaml` declares the Queue service and endpoints.
`compose.addon.yaml` runs managed Queue with private persistent state,
a Core-provided Manager service token, and **no published host ports**.
No separate Queue PIN or browser-session secrets are needed. The
Gateway discovers 14 Queue tools but grants none until reviewed in Manager.
The production and standalone manifests are not modified by this flow.

## Production

See [PRODUCTION.md](PRODUCTION.md). Production keeps the existing SQLite,
service token, DNS aliases, and the single-scheduler invariant. Never mount
the production state directory from staging `compose.yaml`.

## Tests

`bash scripts/test.sh` builds an isolated disposable image and runs unit
and security tests plus an actual unified runtime/MCP smoke test. CI uses
the same suite. Managed browser-to-Manager integration is also covered
in the Core repository.

Back up SQLite using the online backup API (not an isolated live WAL file),
and preserve the credentials needed to restore the deployment.
