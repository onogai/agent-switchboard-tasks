# Managed Task Queue authentication contract

The Queue Web process selects **exactly one mode** at startup:

- **Standalone:** no `TASKS_ADMIN_TOKEN`; Queue verifies its own PIN
  sessions and CSRF, and serves `/queue/`.
- **Managed:** a strong `TASKS_ADMIN_TOKEN` enables the private
  `/internal/queue/api/*` and `/internal/queue/ui/*` endpoints.
  The standalone browser PIN routes are not mounted. Missing or malformed
  managed credentials never trigger a standalone fallback.

## Manager-to-Queue trust boundary

Manager authenticates browser users with its own PIN, session, CSRF and origin
checks. Only Manager forwards management requests on the private network:

- `Authorization: Bearer <TASKS_ADMIN_TOKEN>`
- `X-Switchboard-Session-ID: <opaque Manager session ID>`
- `X-Switchboard-Pin-Version: <current epoch>` for managed approvals

Queue validates the service token before trusting the session ID or serving
managed React assets. The browser never sees the service token, Queue does
not read Manager cookies or PIN verifier, and Manager does not mount Queue's
SQLite state. The separate Gateway controls MCP discovery, OAuth and grants.

Generate an independent token, e.g. with
`python3 -c 'import secrets; print(secrets.token_urlsafe(48))'`,
and keep it private. Deploy the same token to Queue Web, Queue workers and
Manager where relevant.

## Managed automatic approvals

Manager owns the current PIN epoch. Enabling a managed auto-approval captures
that version and the authorizing Manager session identity. Before an
automatic proposal decision, Queue workers validate the epoch through
`POST /admin/internal/queue/validate-pin-version`, using the service token
and `TASKS_AUTHORITY_URL` (normally
`http://infrastructure_admin:8768` in production).

When Manager is unavailable, the token is invalid or the PIN has rotated,
automatic approval **fails closed** and proposals remain pending for manual
review. The stale authorization cannot be silently re-enabled without
new approval. Simultaneous PIN rotation and an in-flight decision can have
a narrow concurrency window, so the Manager authority check must be kept
near the decision.

Standalone deployments use Queue-owned PIN auth and the local one-hour
approval window; they need no Manager authority URL. Do not expose any
managed endpoints publicly. No second manager/Queue user login is required
in the managed UI.
