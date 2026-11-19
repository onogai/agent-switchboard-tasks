# Managed production Queue — one container

The production Queue runs **one Python process** in one Compose service
(`switchboard-tasks`). One Uvicorn server listens on two internal ports
and hosts the same 14 MCP tools, Manager-authenticated HTTP API/UI, and a
single in-process hourly scheduler.

- `tasks_mcp:8771/mcp`: existing Gateway Registry endpoint
- `tasks_web:8767/internal/queue/...`: existing Manager endpoint
- `switchboard-tasks`: one Docker container with both network aliases
- SQLite: existing `TASKS_STATE_ROOT/queue.sqlite3`, including WAL files
- Manager token: existing `TASKS_ADMIN_TOKEN`, unchanged

No host ports are published. The old external `switchboard_addons` network
is reused. The portable `compose.yaml` is a separate staging deployment;
do **not** start it on production state.

## One-time migration from three production containers

From the Queue checkout on the Docker host:

```bash
cd ~/agent-switchboard-tasks
git pull --ff-only
python3 scripts/cutover_single_runtime.py
```

The script first builds the new image **while all three old containers are
running**. It then stops the old scheduler, MCP and Web processes; creates
a private offline backup of the state directory and Compose environment;
starts the single container; verifies health, unchanged SQLite mount,
network aliases, Manager HTTP auth and all 14 MCP tools; and removes only
the three retired containers.

On a cutover failure it removes the candidate and restarts the old
containers. The original image is retained as
`switchboard-tasks:rollback-before-single`; the backup is under
`~/switchboard-cutover-backups/tasks-single-<UTC timestamp>/`.

Do not run `docker compose down -v`, `--remove-orphans` or
`docker system prune` as part of this migration. Never run a second
scheduler against the same SQLite database.

## Private environment

Keep the existing `.env.production` (mode 0600) unchanged:

```dotenv
HOST_UID=<existing numeric UID>
HOST_GID=<existing numeric GID>
TASKS_STATE_ROOT=<absolute existing state directory>
SWITCHBOARD_ADDONS_NETWORK=switchboard_addons
TASKS_ADMIN_TOKEN=<existing Queue/Manager shared token>
ALLOWED_GOOGLE_EMAIL=<existing allowed email>
```

Do not print, commit or rotate the shared token. The production runtime
requires managed mode and fails closed if the token is missing or weak.

## Routine updates

```bash
cd ~/agent-switchboard-tasks
git pull --ff-only
docker compose -p switchboard-tasks --env-file .env.production \
  -f compose.production.yaml up -d --build tasks
docker compose -p switchboard-tasks --env-file .env.production \
  -f compose.production.yaml ps
```

The Queue image still contains the independent MCP, Web and tick modules
for staging/compatibility, but production launches only
`python -m task_queue.runtime`. Do not launch those entrypoints separately
against the production database.
