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

When opened from the main Switchboard Admin **Queue** tab, the managed React UI
runs in a same-origin protected frame. Manager owns the common top navigation
and Queue shows only its compact local sections (Overview, Queue, Rules,
Proposals). Opening `/admin/queue/` directly retains the independent
sidebar and the return link, while standalone `/queue/` keeps its normal
PIN-protected interface. UI embedding does not change scheduler behaviour,
state ownership or service authentication.

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

## Rule organization

Rules may have an optional `group` (trimmed, blank or null means ungrouped).
The Rules UI hides archived rules by default and groups visible rules without
changing their execution settings. `list_task_rules` excludes archived rules
unless `include_archived=true`; `is_active` remains an independent filter.
`get_task_rule` still reads archived rules. `version` is the optimistic-lock
revision used by proposals; `execution_version` tracks the revision used by
execution snapshots (`definition_version` on instances). Metadata-only group
changes advance `version` but not `execution_version`, even across restarts.
