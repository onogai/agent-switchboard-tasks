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
