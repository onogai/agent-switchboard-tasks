# Independent Task Queue add-on

Contains Task Queue scheduler, 14-tool FastMCP HTTP server, SQLite state, PIN web UI and React assets. No `gateway` or `infrastructure_admin` package is needed in the standalone image. The historical PIN verifier has been copied into `task_queue.auth` so existing verifier state can migrate.

## Disposable verification

Run `bash scripts/test.sh`. This builds an isolated image, validates the MCP tool catalog, initializes a temporary Queue SQLite DB and checks that the React UI was compiled. No host state or secrets are mounted.

## Staging

Create a private Docker network shared with Gateway, e.g. `docker network create switchboard_addons`, or set `SWITCHBOARD_ADDONS_NETWORK`. Configure `QUEUE_WEB_PIN_PEPPER` and `QUEUE_WEB_SESSION_SECRET` in a local (untracked) `.env`. Use a fresh `./state` directory for staging.

Only after backing up existing `queue.sqlite3` (including a consistent WAL snapshot), copy the production queue and PIN verifier state to the new repo's state directory with appropriate permissions. The same original verifier, pepper and session secret are required to keep current PIN validity. The SQLite database contains active leases and proposals: never run old and new schedulers against the same DB during cutover.

Gateway cutover is a separate, explicit step. Existing public tool names and profile grants must be migrated transactionally, and `GATEWAY_TASKS_EXTERNAL=1` enabled together with the source migration. Do not expose the unauthenticated MCP port publicly.
