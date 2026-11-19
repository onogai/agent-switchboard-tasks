# Independent production Task Queue

This deployment owns the Queue MCP, Web/API and **one** scheduler.
It is independent of Gateway Core and Manager, and uses the existing
`switchboard_addons` Docker network and the existing Queue database.

The portable `compose.yaml` is for fresh standalone installations only.
Use `compose.production.yaml` for the managed production instance.

## Private environment

Create `.env.production` locally, mode 0600, with these keys:

```dotenv
HOST_UID=<numeric UID>
HOST_GID=<numeric GID>
TASKS_STATE_ROOT=/home/onogai/agent-switchboard-tasks/state
SWITCHBOARD_ADDONS_NETWORK=switchboard_addons
TASKS_ADMIN_TOKEN=<existing Queue/Manager shared service token>
ALLOWED_GOOGLE_EMAIL=<existing allowed email>
```

Preserve the existing token. Do not commit or print the file, and do not
create a new token without changing Manager in the same operation.

For an existing live deployment, obtain `TASKS_ADMIN_TOKEN` from the
currently running Queue container **without echoing it**. Preserve the
existing `queue.sqlite3` directory and all WAL files.

## Deploy

Before the first deployment, build the new image while the old Queue is
still running:

```bash
docker compose -p switchboard-tasks --env-file .env.production \
  -f compose.production.yaml config --quiet
docker compose -p switchboard-tasks --env-file .env.production \
  -f compose.production.yaml build tasks_mcp
```

Stop the three original Queue containers individually, including the
scheduler, before starting the new ones. Never run two schedulers on the
same SQLite database.

```bash
docker compose -p switchboard-tasks --env-file .env.production \
  -f compose.production.yaml up -d --no-build tasks_mcp tasks_tick tasks_web
docker compose -p switchboard-tasks --env-file .env.production \
  -f compose.production.yaml ps
```

The Compose services retain internal DNS names `tasks_mcp` and
`tasks_web` on the add-ons network. Manager reaches
`http://tasks_web:8767`; Queue reaches Manager at
`http://infrastructure_admin:8768`. The Queue database is bind-mounted
from the existing state directory; no database copy is required.

Verify the Queue API via Manager, a Queue MCP call, and a single active
scheduler. Remove old stopped containers only after verification. Do not
remove the former shared Compose project or its external networks while
other services are still using them.

## Routine updates

```bash
git pull --ff-only
docker compose -p switchboard-tasks --env-file .env.production \
  -f compose.production.yaml up -d --build tasks_mcp tasks_tick tasks_web
```

Preserve a consistent SQLite snapshot and the existing service token
before upgrades. Avoid `down -v`, broad orphan removal and starting
staging Compose against production state.
