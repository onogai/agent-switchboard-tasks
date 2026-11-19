# Task Queue production

The managed production instance is one Docker container,
`switchboard-tasks`, running `python -m task_queue.runtime`.

- One process, one hourly scheduler
- MCP endpoint `http://tasks_mcp:8771/mcp`
- Manager endpoint `http://tasks_web:8767/internal/queue/*`
- One persistent `TASKS_STATE_ROOT/queue.sqlite3` database and unchanged
  `TASKS_ADMIN_TOKEN`
- No published host ports

## Private host configuration

Keep `.env.production` at mode 0600 with:

```dotenv
HOST_UID=<numeric UID>
HOST_GID=<numeric GID>
TASKS_STATE_ROOT=<absolute existing state directory>
SWITCHBOARD_ADDONS_NETWORK=switchboard_addons
TASKS_ADMIN_TOKEN=<existing Queue/Manager service token>
ALLOWED_GOOGLE_EMAIL=<approved Google account>
```

Do not print or rotate the shared service token casually; Manager uses it
to authenticate proxy requests. Use `compose.production.yaml`, **not**
the disposable `compose.yaml`, for production.

## Routine commands

```bash
cd ~/agent-switchboard-tasks
git pull --ff-only
docker compose -p switchboard-tasks --env-file .env.production \
  -f compose.production.yaml config --quiet
docker compose -p switchboard-tasks --env-file .env.production \
  -f compose.production.yaml up -d --build tasks
docker compose -p switchboard-tasks --env-file .env.production \
  -f compose.production.yaml ps
```

Before an upgrade, back up the existing SQLite database consistently and
retain a matching copy of the private environment. Do not start a second
scheduler on the same database, use `down -v`, or prune shared networks.
The original three-container cutover was completed in November 2026;
its one-off migration script is retained in Git history, not the active
operational tree.

For an isolated developer deployment, provide the standalone PIN/session
secrets and use `docker compose -f compose.yaml up -d --build tasks`
on a disposable `./state` directory and the configured private network.
