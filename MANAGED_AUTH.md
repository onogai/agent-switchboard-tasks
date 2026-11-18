# M7 management authentication contract

When `TASKS_ADMIN_TOKEN` is set to a strong 32+ character secret, the Queue
Web process operates in **managed-only** mode. The standalone browser routes
(`/queue/api/login`, local PIN checks, UI) are not mounted.

Switchboard Admin authenticates a browser once using its own PIN session and
checks CSRF/Origin for writes. Its server then calls the Queue private HTTP API
on the Docker network:

- Prefix: `/internal/queue/api/*`
- Header: `Authorization: Bearer <TASKS_ADMIN_TOKEN>`
- Header: `X-Switchboard-Session-ID: <opaque session id>`
- Body: same JSON contract as the standalone Queue APIs.
- Endpoint set: existing Queue management actions excluding login/session/logout.

The service token is **not** a browser token. Queue checks it on every request;
the session ID is trusted only after service-token validation and binds
approval/auto-approval operations to the central browser session. The Queue
service never reads Manager cookies, Manager PIN data, or Gateway SQLite.

Invalid/missing tokens or browser session IDs return 401; no automatic fallback
to standalone occurs. If the secret is unset, only standalone PIN auth is enabled.
A malformed nonempty secret fails startup rather than exposing another mode.

Generate an independent token with:
`python3 -c 'import secrets; print(secrets.token_urlsafe(48))'`

Set the **same** token in Manager and Queue Web on their private network.
Do not use this token for the Task Queue MCP endpoint; existing MCP grants and
OAuth policy remain Gateway responsibilities.

## M8 managed auto-approval revocation

Managed Queue Web requires `TASKS_AUTHORITY_URL` and `TASKS_ADMIN_TOKEN` to
enable one-hour auto-approval. Manager forwards its current PIN version as
`X-Switchboard-Pin-Version`; Queue stores the version alongside the session
identity. The Queue MCP worker needs the **same** `TASKS_AUTHORITY_URL` and
`TASKS_ADMIN_TOKEN` environment variables, not just Queue Web.

Before automatically accepting a proposal, the worker checks the version via
the Manager private endpoint
`POST /admin/internal/queue/validate-pin-version` using the service token.
If Manager is unavailable, credentials fail or PIN was changed, the proposal
remains pending. No standalone PIN fallback is attempted in managed mode.

Standalone Queue installations omit these managed env variables entirely and
continue to use their own PIN and one-hour approval window. Do not expose
`TASKS_AUTHORITY_URL` publicly; in Switchboard Compose use the private
`http://infrastructure_admin:8768` service address.

The Manager PIN validator is an authorization check for a single proposal
decision; in-flight decisions can have a narrow concurrency window during
simultaneous Manager PIN rotation.
