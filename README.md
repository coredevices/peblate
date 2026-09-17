# Peblate

An installable Django extension for stock Weblate: PebbleOS watch previews,
font and license uploads, coverage checks, and draft universal language packs.
No Weblate fork or separate translator application.

## Install in Weblate

Install the `peblate` and `pebbleos-translations` wheels into Weblate's Python
environment (these packages are not published to a package index yet):

```sh
uv pip install --python /path/to/weblate/venv/bin/python /path/to/wheels/*.whl
```

Add to Weblate's settings, after its existing settings:

```python
INSTALLED_APPS = ["peblate", *INSTALLED_APPS]
ROOT_URLCONF = "peblate.urls"
PEBLATE_COMPONENT = "pebbleos/watch"  # your project/component
PEBLATE_CACHE_ROOT = "/var/lib/weblate/peblate"  # shared by web and worker processes
CELERY_BEAT_SCHEDULE = {
    **globals().get("CELERY_BEAT_SCHEDULE", {}),
    "peblate-cleanup": {"task": "peblate.tasks.cleanup_jobs", "schedule": 3600.0},
}
```

Run `weblate migrate` and `weblate check`, collect static files using your normal Weblate deployment
procedure, and restart its web and worker processes. For the official Docker
image, [the example](examples/docker/README.md) installs wheels in a thin derived
image and supplies these settings. Weblate itself stays unmodified.

One component is supported per installation; give it a dedicated preview-cache directory.
Access follows Weblate’s component and language permissions. Preview needs
`translation.download`; font changes also need `unit.edit` and `upload.perform`;
validation and draft builds need `unit.edit`. Read-only viewers see disabled
mutation controls, and every endpoint checks permissions independently. Source
English is handled by firmware, so Peblate’s pack controls are hidden there.

## Build

```sh
uv build --wheel
```

Build the standalone tools wheel in `pebbleos-translations` with the same command.
The installed extension imports that package; it needs no translation checkout,
firmware checkout, SDK, or source mounts. Pack compilation requires GNU gettext
(`msgfmt`), which the Weblate image already provides.

Include the renderer artifact before building a wheel: place the PebbleOS
`tools/text2wasm` output (`renderer.js`, `GOTHIC*.pbf`, `revision.txt`) in
`src/peblate/static/pebble/renderer/`. See [renderer instructions](renderer/README.md).
The renderer source belongs to PebbleOS; versioned CI artifact distribution remains
future work. Generated artifacts are ignored in Git and bundled in the wheel.

## Boundaries

- **Weblate:** accounts, catalog editing, language creation, and Git synchronization.
- **Peblate:** editor sidebar, font/license repository commits, preview endpoints, draft checks/builds.
- **pebbleos-translations:** independent catalog/font/pack tools and coverage/baseline data.
- **PebbleOS:** firmware rendering code and the WASM artifact.

The UI overrides the editor and new-language templates and adds JavaScript; Weblate model access
is isolated in `weblate_adapter.py`. This is a Django extension, not just an event
add-on: event hooks alone cannot supply the editor UI. Tested against Weblate
**2026.9.1**; a system check warns on other versions. Weblate's internal API is not
stable, so run the integration smoke test before upgrades.

## Remaining work

Complete watch-screen previews, automated source POT uploads, and
reviewed pack publication/mobile distribution. Fonts, licenses, and maps are versioned in the component’s repository; downloads
are drafts. Automatic validation can later
use a Weblate add-on event hook.

## Git storage

Uploads commit the font, mandatory license, and the language's `lang_map.json`
together in Weblate's component checkout, under Weblate's repository lock.
Each regional folder (such as `he_IL/`) holds its catalog, map, and hashed font
and license files. Styles in a language share local filenames; identical files
across languages share Git blobs, while remaining local in a checkout.
Maps sit beside their catalogs and are created on the first upload
or pack check. Unassigned slots use the watch's base fonts.

Repeated identical assignments create no additional commit. Asset commits exclude
unrelated staged translations; failed commits restore the previous files. These
operations do not push. Git synchronization remains Weblate's responsibility.
Compiled preview fonts live only in `PEBLATE_CACHE_ROOT`, outside the checkout;
a fresh clone plus the standalone tools is sufficient to build a language pack.

The local example remains disposable and has no upstream Git remote. Existing
prototype service-only uploads are not automatically imported; re-upload any demo
fonts you want to retain. This is not a migration of the test instance to production.

The example configures Weblate’s `posix_long` language-code style, so new catalog
folders include a country code (`de_DE`, `fr_FR`, `he_IL`, etc.). Downloads use the
catalog folder’s locale too. `en_IL` remains English with Hebrew glyph coverage;
it is not an alias for Hebrew.

## Translator guidance

New-language setup reviews font requirements before submitting Weblate’s native
language-creation form. The project-level **+ / New translation** also opens this
wizard when the configured component is the only eligible component; projects
with multiple eligible components retain Weblate’s native selection flow. Missing fonts do not block starting a translation; fonts
and licenses are supplied in the editor.

The editor explains the steps from a new language to a draft pack. Initial font
advice uses the selected language's character baseline and actual built-in glyph
coverage. The font panel lists assignments and can reuse a font with its existing
license across text styles. Coverage results show missing characters and examples,
with a direct action to select the affected style. Font changes invalidate the
last check; unsaved translations must be saved before checking or building.

Previews follow the active translation field, including plural forms. They render
a sample text box; full-screen layout review and publication approval remain
separate from successful draft-build checks.

## Background checks and drafts

Checks and draft builds run on Weblate's existing Celery workers. Web and worker
processes must share `PEBLATE_CACHE_ROOT`. Keep the default Celery queue worker
and beat scheduler running; no separate Peblate service is needed.

The editor shows progress and links to a job page. Each job snapshots saved
translations and fonts when the worker starts; later edits require a new job.
Concurrent requests for the same operation by the same user reuse the active job.
Completed drafts have an explicit download link and are never published.

Results belong to the requesting user, and viewing or downloading them rechecks
current Weblate permissions. Failed or stalled jobs can be retried with a fresh
snapshot. Checks and builds have time limits; the hourly cleanup task removes
results after 24 hours.

The [source import guide](docs/source-sync.md) describes native Weblate uploads
of release-generated POT files. Source templates are committed alongside catalogs.
Hosted release uploads remain to be connected.
