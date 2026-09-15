# Local Weblate example

Run these commands from the Peblate repository root. This example uses a pinned
stock Weblate image with the two installed wheels, plus PostgreSQL and Valkey.
Only localhost port 8088 is exposed. The component uses regional locale folders
via Weblate’s `posix_long` setting; fonts and licenses stay inside each folder.

```sh
uv run --no-project --with polib==1.2.0 python examples/docker/setup.py
uv build --wheel --out-dir examples/docker/wheels
uv build --wheel ../pebbleos-translations --out-dir "$PWD/examples/docker/wheels"
docker compose --env-file .env -f examples/docker/compose.yaml up -d --build
# After initial database migrations:
docker compose --env-file .env -f examples/docker/compose.yaml exec -T weblate \
  weblate shell < examples/docker/bootstrap.py
```

Prepare the [renderer artifact](../../renderer/README.md) before building the
Peblate wheel. `TRANSLATIONS_PATH` can select the catalog checkout for setup;
that checkout is used only to create the local seed, never mounted as runtime tools.
The demo POT comes from existing French msgids, not current firmware extraction.
Bootstrap preserves existing edits and configures no upstream Git remote.

Sign in as `admin` using `ADMIN_PASSWORD` in the ignored root `.env`. Select a
language in Weblate's editor, then use the Watch preview sidebar. Fonts require
an accompanying license. Save translations before downloading a draft pack.

Integration test (a disposable repository clone and preview cache):

```sh
docker compose --env-file .env -f examples/docker/compose.yaml exec -T weblate \
  weblate shell < examples/docker/smoke.py
```

The test compares a draft download with a pack built from a fresh Git clone.
It expects Hebrew/French demo catalogs and Heebo fixtures. Setup copies
those fixtures from the translation checkout. Generated seed and credentials stay
in the ignored root `runtime/` and `.env`; fixtures and wheels are also ignored.
The Compose project name remains `pebble-weblate-prototype` to preserve existing
volumes. Use the same Compose command with `down` to stop without deleting data.

To seed the Hebrew font example into this disposable repository:

```sh
docker compose --env-file .env -f examples/docker/compose.yaml exec -T weblate \
  weblate shell < examples/docker/seed_fonts.py
```

This refuses a component with a non-local repository or any Git remote, and skips
styles that already have an assignment. It does not migrate the old service storage.

## Test translator and reviewer accounts

After bootstrap, configure the private disposable project and its native review workflow:

```sh
docker compose --env-file .env -f examples/docker/compose.yaml exec -T weblate \
  weblate shell < examples/docker/setup_accounts.py
docker cp pebble-weblate-prototype-weblate-1:/app/data/peblate-demo-accounts.json runtime/demo-accounts.json
chmod 600 runtime/demo-accounts.json
```

The ignored credentials file contains random passwords for these non-admin users:

- `peblate-translator`: translate, start languages, preview, upload fonts/licenses, and build drafts.
- `peblate-reviewer`: the same actions plus native string approval.
- `peblate-viewer`: read-only previews; no uploads, checks or builds.
- `peblate-french-only`: translator permissions restricted to French.
- `peblate-outsider`: no project access.

This setup refuses repositories with remotes and never changes the administrator.
Run the permission tests after setup (uploads use a disposable repository clone):

```sh
docker compose --env-file .env -f examples/docker/compose.yaml exec -T weblate \
  weblate shell < examples/docker/permission_smoke.py
```

These are example accounts and settings for testing, not production provisioning.

`workflow_smoke.py` additionally creates the Italian demo language if absent,
saves “Music” as “Musica” through Weblate’s native editor, approves it as the
reviewer, and downloads `it_IT.pbl`. It refuses to replace a different existing
translation for that string. Run it with the same `weblate shell` command.

`background_smoke.py` tests concurrent requests, fixed snapshots, access checks,
retries, timeouts, and cleanup using a disposable repository and a mocked queue.
`workflow_smoke.py` additionally queues a real job and waits for the installed
Celery worker to finish, so run it after restarting the updated web and workers.
Both use the same `weblate shell` command above. The example schedules hourly
cleanup and shares job files through its existing Weblate data volume.
