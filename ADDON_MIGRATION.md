# Migrating a live production Queue into a Switchboard add-on

## Managed Queue UI (November 2026)

The Queue React frontend already belongs to this repository. The production
schema-v2 manifest now exposes its UI through Switchboard's generic,
PIN-protected `/admin/addon-ui/tasks/` route. Existing rule, task, attempt and
proposal records remain in Queue SQLite; no UI-specific data migration exists.

Before starting, update the Switchboard Core/Manager to a release containing
generic UI query/session forwarding and staged-cutover UI registration.
**Do not run the new Queue image against the legacy Queue database while the
old scheduler is running.**

The safe sequence is:
1. Stage `tasks` using the command below. Its database starts empty and its
   MCP source is not registered. Confirm that the legacy Queue still runs.
2. Optionally run `./switchboard addon ui-sync tasks` to preview the *empty*
   new Queue UI without switching MCP tools. This adds a second Queue tab.
3. Stop both Queue containers, perform the already documented offline SQLite
   and service-token migration, and start **only** the managed add-on.
4. Run `./switchboard addon cutover tasks --dry-run` before cutover. The
   successful cutover automatically registers the new UI (or refreshes the
   earlier preview registration) with the **migrated** token. No special
   Manager proxy configuration is needed for the new tab.
5. Confirm the new UI shows the actual rules, instances and proposals, that
   filters and mutations work, and that the managed Queue has exactly one
   scheduler. Existing MCP tools/grants stay associated with source `tasks`,
   but contract reapproval is required after rebind.
6. Only **after** acceptance, remove the Manager's legacy `/admin/tasks` tab,
   `/admin/queue` asset route and `/admin/api/queue/*` proxy in Switchboard
   Core. Do not remove those paths before the legacy cutover is completed.

The managed UI reuses the existing Manager language setting
`switchboard.admin.locale` (en, uk, es-ES). `addon uninstall tasks` archives
the installed state by default; it is **not** a safe shortcut to discard a
live production Queue. For rollback, follow the reverse SQLite migration below,
then use the documented cutover rollback; the managed UI registration is removed
when routing is switched back to the legacy Queue.


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

After copying the production token, **do not use `./switchboard addon start tasks`**.
The staged container was created with a different generated
`TASKS_ADMIN_TOKEN` environment value. Docker `start` (and Compose
`restart`) reuses that stale container environment; the new Queue API will
reject Manager requests even though the migrated secret file is correct.
Recreate **only** the stopped add-on Queue container from its existing
manifest and updated private `config.env`, without rebuilding or touching
legacy services:

    cd ~/agent-switchboard
    docker compose -p switchboard-addon-tasks \
      --project-directory "$PWD/addons/tasks/source" \
      --env-file "$PWD/addons/tasks/config.env" \
      -f "$PWD/addons/tasks/source/compose.addon.v2.yaml" \
      up -d --no-deps --force-recreate --wait queue
    ./switchboard addon cutover tasks --dry-run

Verify the recreated container is healthy, the migrated rule/instance/attempt/
proposal counts match the source snapshot, and the **actual** Manager API
authentication succeeds. Avoid printing `docker inspect` environment or
service tokens; the old Queue must remain stopped.

Verify the real Queue's rule, instance, attempt and proposal counts;
test the 14 tool names and Manager API authentication. Then cut over:

    ./switchboard addon cutover tasks

Registry keeps source ID tasks, stable tool IDs and grants. The existing
contracts enter review and need reapproval in Manager before agents can
use them again.

The new UI does **not** need SWITCHBOARD_TASKS_ADMIN_URL. The old
Manager Queue tab continues using that legacy variable until it is removed.
You may point it at http://addon-tasks:8767 temporarily (keeping the existing
Manager token) if old Queue UI/API compatibility is required during acceptance.
After completing acceptance, remove the legacy tab/proxy and related settings.

    ./switchboard production doctor

Keep the old switchboard-tasks container stopped but intact until the
Manager Queue UI, jobs, single scheduler, grants, rollback and backup
have been verified.

## 4. Rollback without losing newer task history

**Schema v3 or later:** the legacy schema-v2 runtime cannot open the updated database. The reverse-copy helper refuses this downgrade. Use the managed add-on safe-state backup/restore procedure instead; review post-backup task history and external side effects before restoring.

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

## 5. Optional legacy container cleanup after acceptance

Once the **new** managed Queue UI, 14 granted tools, scheduler, backup and
`production doctor` have passed, the old **stopped** `switchboard-tasks`
container may be removed. It is not the live Queue and is not required by
managed production backups. Do **not** use `docker compose down -v`, or
remove the legacy SQLite state, old `.env.production`, Compose manifest or
source checkout if reverse migration remains a desired emergency option.

    # Confirm the legacy container is stopped, then remove only that container.
    test "$(docker inspect -f '{{.State.Running}}' switchboard-tasks)" = false
    docker rm switchboard-tasks

The test/development Queue under a separate Compose project is unrelated.

### Reverse migration if the legacy container has been removed

The migration helper still intentionally requires the legacy container to
**exist but be stopped** when `--reverse --commit` runs. Recreate the
container from the saved old deployment, without starting its scheduler:

    cd ~/agent-switchboard
    ./switchboard addon stop tasks

    cd ~/agent-switchboard-tasks
    docker compose -p switchboard-tasks --env-file .env.production \
      -f compose.production.yaml create --no-build --no-deps tasks
    docker update --restart=no switchboard-tasks

Then run the `--reverse` preview and confirmed offline copy described in
section 4 **while both schedulers are stopped**. Only after the copy succeeds
should the legacy scheduler start. The subsequent Registry handoff
(`./switchboard addon rollback tasks`) requires that old MCP endpoint to
be live, and the Manager's legacy Queue routing/UI must also be restored
separately.

This is an emergency **legacy runtime** rollback, not the preferred routine
recovery of a healthy managed Queue. For managed-Queue incidents, first
consider restoring the current managed deployment/state from a verified
production backup. Do not delete the old checkout, env or state based solely
on this container cleanup; doing so would retire this reverse-migration path.
