# Peblate

A Django extension for Weblate that adds PebbleOS watch previews, font uploads,
coverage checks and draft language packs. Catalog and pack tools live in
[pebbleos-translations](https://github.com/coredevices/pebbleos-translations).

## Translating

New-language setup prepares fonts and reviews rendering before creating the
translation. Languages covered by built-in fonts need no upload. The wizard
also offers compatible fonts and licenses from existing English `en_*` font-only
packs, which remain hidden as translation targets.

In the editor, keep translations concise and check the watch preview. Save your
changes before checking coverage or building a draft. Drafts include strings
awaiting approval; strings marked as needing editing and unaccepted suggestions
are excluded. Previews show a sample text box, so full watch layouts still need
testing on a watch.

Contributors can fill empty font styles and replace their own uploads. Replacing
another contributor's font, or an imported font without an owner, requires
`unit.review` for that language or a superuser. Uploads require a license;
advanced font controls in the editor handle later corrections.

## Publication

The editor links to **Language pack publication**. Project maintainers enable
publication and approve new or changed custom fonts there. Built-in body and
heading fonts are checked automatically; they need no manual approval.
Language reviewers approve wording through Weblate's native review workflow and
language-scoped teams.

Published updates require a language reviewer, at least 80% approved strings,
passing build checks and approval of any custom fonts. Only approved strings ship.
Languages without reviewers remain community drafts; held updates retain their
previous published pack. English font-only packs need font approval and coverage
checks, but no wording reviewer.

Decisions are stored in Weblate. The automated publisher in
`pebbleos-translations` reads them through Peblate's authenticated, read-only API.
Draft downloads are for testing and do not publish a pack.

## Installation

Install the `peblate` and `pebbleos-translations` wheels in Weblate's Python
environment. They are not yet published to a package index:

```sh
uv pip install --python /path/to/weblate/venv/bin/python /path/to/wheels/*.whl
```

Add these settings after Weblate's existing settings:

```python
INSTALLED_APPS = ["peblate", *INSTALLED_APPS]
ROOT_URLCONF = "peblate.urls"
PEBLATE_COMPONENT = "pebbleos/watch"
PEBLATE_CACHE_ROOT = "/var/lib/weblate/peblate"
CELERY_BEAT_SCHEDULE = {
    **globals().get("CELERY_BEAT_SCHEDULE", {}),
    "peblate-cleanup": {"task": "peblate.tasks.cleanup_jobs", "schedule": 3600.0},
}
```

Run `weblate migrate`, `weblate check` and static-file collection, then restart
Weblate's web and worker processes. After configuring the component, run
`weblate peblate_configure_languages` to exclude English font-only catalogs from
translation discovery and creation while retaining their files for pack builds.

One component is supported per installation. Web and Celery workers must share
the writable cache directory; keep the default queue worker and beat scheduler
running. Jobs snapshot saved translations and fonts, recheck permissions on
access, and expire after 24 hours.

Access uses Weblate's component and language permissions. Previews require
`translation.download`; draft checks and builds also require `unit.edit`; font
changes additionally require `upload.perform`. Publication controls require
project management permission.

Configure [Pebble Accounts](docs/pebble-login.md) for Pebble-only signup.
Registration is closed by default; existing accounts retain password login and
recovery. See the [source import guide](docs/source-sync.md) for firmware POT
updates through Weblate's native API.

## Development

Prepare the [PebbleOS renderer artifact](renderer/README.md) before building.
Its generated files are ignored in Git and bundled in the wheel:

```sh
uv build --wheel
```

Build the `pebbleos-translations` wheel separately. The installed extension needs
GNU gettext (`msgfmt`, included in the Weblate image), but no firmware checkout
or SDK. The [local Docker example](examples/docker/README.md) provides setup and
integration tests.

Tested with Weblate **2026.9.1**. Peblate overrides editor and language-creation
templates and uses Weblate's internal APIs; run integration tests before upgrades.

Fonts, licenses and maps are committed together in Weblate's component checkout.
Uploads use content hashes, share identical assets and leave pushing to Weblate.
Replacing fonts removes tracked font assets and licenses that no map still uses.
Compiled fonts, previews and job results stay in the cache. Draft builds use
private snapshots and do not commit translations or change their approval state.
