# Migrating a live production Queue into a Switchboard add-on

This is a planned-downtime operation. Production Queue has one scheduler,
a live queue.sqlite3 database, Manager UI/service token and 14 granted
MCP tools. Never start two Queue schedulers on one database.

Prerequisites: Switchboard one-service schema-v2 support, staged source
cutover, lifecycle start/stop, and a production doctor and backup that
recognize an active managed Queue. The existing v1 portable package stays
unchanged; production selects switchboard-addon.production.yaml.

## 1. Stage independently, with legacy Queue still running

Run from ~/agent-switchboard:

    ./switchboard addon install https://github.com/onogai/agent-switchboard-tasks.git --name tasks --target production --stage-for-replacement
    ./switchboard addon logs tasks
    ./switchboard addon cutover tasks --dry-run

The new Queue initially runs against an empty, isolated database, and
is NOT registered in the Gateway. Its scheduler has no configured rules.
The real source tasks, production scheduler and all grants stay untouched.
The fresh Manager token differs from the production Manager token; that
is intentionally repaired during offline migration.

## 2. Stop both Queue runtimes

Run:

    cd ~/agent-switchboard
    ./switchboard addon stop tasks

    cd ~/agent-switchboard-tasks
    docker compose -p switchboard-tasks --env-file .env.production -f compose.production.yaml stop tasks

Do not use down -v and do not remove the legacy state or source.

Preview the migration:

    python3 scripts/migrate_addon_state.py --legacy-env "$HOME/agent-switchboard-tasks/.env.production" --addon-root "$HOME/agent-switchboard/addons/tasks"

Run the migration only after both containers are stopped:

    python3 scripts/migrate_addon_state.py --legacy-env "$HOME/agent-switchboard-tasks/.env.production" --addon-root "$HOME/agent-switchboard/addons/tasks" --commit --confirm tasks

The script makes a consistent SQLite backup, validates schema, integrity
and per-table row counts, archives previous staging DB files, and copies
the database into the isolated add-on state. The original production
database remains untouched. It also copies the preexisting production
TASKS_ADMIN_TOKEN into the add-on's protected config.env and secret file,
without printing it or putting it in command arguments.

## 3. Start the migrated Queue and switch routing

Run from ~/agent-switchboard:

    ./switchboard addon start tasks
    ./switchboard addon cutover tasks --dry-run

Verify the real Queue's rule, instance, attempt and proposal counts;
test the 14 tool names and Manager API authentication. Then cut over:

    ./switchboard addon cutover tasks

Registry keeps source ID tasks, stable tool IDs and grants. The existing
contracts enter review and need reapproval in Manager before agents can
use them again.

Set SWITCHBOARD_TASKS_ADMIN_URL=http://addon-tasks:8767 in the private
~/agent-switchboard/.env.production. Preserve the existing Manager token.

    ./switchboard production up -d --no-deps gateway_manager
    ./switchboard production doctor

Keep the old switchboard-tasks container stopped but intact until the
Manager Queue UI, jobs, single scheduler, grants, rollback and backup
have been verified.

## 4. Rollback without losing newer task history

An endpoint-only rollback would lose work completed after the database
migration. Stop both Queue containers first. Use the same helper with
--reverse to preview and then copy the latest add-on database back to
the legacy production state, preserving backups on both sides:

    python3 scripts/migrate_addon_state.py --legacy-env "$HOME/agent-switchboard-tasks/.env.production" --addon-root "$HOME/agent-switchboard/addons/tasks" --reverse
    python3 scripts/migrate_addon_state.py --legacy-env "$HOME/agent-switchboard-tasks/.env.production" --addon-root "$HOME/agent-switchboard/addons/tasks" --reverse --commit --confirm tasks

Then start only the legacy Queue, run addon rollback tasks, restore
Manager TASKS_ADMIN_URL to http://tasks_web:8767 and recreate the Manager
container. Reapprove contracts as required.

Migration is not finished until the production doctor and backup are
updated to follow the actual live Queue deployment.
