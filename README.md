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
PEBLATE_CACHE_ROOT = "/var/lib/weblate/peblate"  # writable preview-cache directory
```

Run `weblate check`, collect static files using your normal Weblate deployment
procedure, and restart its web and worker processes. For the official Docker
image, [the example](examples/docker/README.md) installs wheels in a thin derived
image and supplies these settings. Weblate itself stays unmodified.

One component is supported per installation; give it a dedicated preview-cache directory.
The current UI and endpoints remain **superuser-only**. Shared translator permissions
are still to be implemented before a public deployment.

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

The UI uses one template override and `editor.js` selectors; Weblate model access
is isolated in `weblate_adapter.py`. This is a Django extension, not just an event
add-on: event hooks alone cannot supply the editor UI. Tested against Weblate
**2026.9.1**; a system check warns on other versions. Weblate's internal API is not
stable, so run the integration smoke test before upgrades.

## Remaining work

Translator permissions, background jobs, complete watch-screen previews, automated source POT uploads, and
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
