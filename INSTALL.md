# Install and operate the Task Queue add-on

Task Queue is independently packaged: no Gateway or Manager Python module is
required in its image. Its database contains rules, task instances, proposals
and leases. The standalone and managed modes share these business operations.

## Test before deployment

Run `bash scripts/test.sh` from this checkout. The smoke test builds an
isolated image and runs Python tests in disposable containers without binding
a production database or credentials.

## Standalone installation

Use this repository's `compose.yaml` only for a **new standalone deployment
or disposable staging environment**, never as a replacement for the existing
production Switchboard Compose project.

1. Create a private Docker network (or set `SWITCHBOARD_ADDONS_NETWORK`).
2. Provide `HOST_UID`, `HOST_GID`, a new 32+ character
   `QUEUE_WEB_PIN_PEPPER` and `QUEUE_WEB_SESSION_SECRET` in a private
   `.env`, and initialize the standalone PIN verifier.
3. Use a fresh `./state` directory and restrict access to it.
4. Build the image and start the intended services from this Compose file.
   Keep `tasks_mcp` and `tasks_web` private; the sample Web binding is
   loopback-only.
5. Verify the Queue PIN login, MCP catalog, Queue UI and one scheduler.

Keep private tokens and SQLite state outside Git; never reuse production
credentials for disposable staging.

## Switchboard-managed deployment

The existing modular production was cut over on **18 November 2026**; its
Core-owned `compose.yaml` coordinates the running Queue services. Do not
deploy this repository's standalone Compose into that project, start a second
scheduler, or recreate any containers solely because Git sources changed.

Managed mode is activated for the Web process by a strong 32+ character
`TASKS_ADMIN_TOKEN`, shared with Manager over the private Docker network.
Configure `TASKS_AUTHORITY_URL` and the same token on **Queue Web, MCP
worker and scheduler** wherever auto-approved proposals may be processed.
In production, Manager is reachable at
`http://infrastructure_admin:8768`. Managed mode does not mount Manager's
`admin.sqlite3` and never accepts a Queue-local PIN fallback.

Manager verifies user PIN and CSRF, proxies JSON and React assets, and
exposes the managed Queue at `/admin/queue/`. Gateway owns OAuth, public MCP
contracts and grants; Queue never owns or edits Gateway SQLite.

### Preserving an existing installation

- Keep the original `queue.sqlite3` and any WAL state consistent; back up
  before data migrations or container recreation.
- Preserve Manager PIN verifier/pepper and `TASKS_ADMIN_TOKEN`. Changing
  them without coordinated updates can lock out managed actions.
- Preserve the Gateway registry mappings and 14 public Queue tool contracts.
- Stop old writers before a database restore or transfer. Never run two tick
  processes against the same Queue database.
- Deploy only named services from the Core production Compose after validating
  images, paths and secrets. Never use global `compose up/down` or
  `--remove-orphans` against the live project.

See [MANAGED_AUTH.md](MANAGED_AUTH.md) for the token, session and PIN-epoch
contract. Historical cutover scripts are intentionally not prerequisites for
a new deployment; older migration history remains in Git.
