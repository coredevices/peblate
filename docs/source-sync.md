# Released translation sources

Use stock Weblate's PO format with `new_base=pebbleos.pot` and the regional
catalog mask `*/tintin.po`. The release-generated POT is committed to
`pebbleos-translations` alongside catalogs. It is the template for new languages;
standalone pack builds still use only the selected language's catalog and assets.

After a successful firmware release, CI can upload its merged POT to:

```text
POST /api/translations/pebbleos/watch/en/file/
Authorization: Token <Weblate service-account token>

multipart fields:
  method=source
  file=<released pebbleos.pot>
```

Weblate commits pending translations, merges source changes into existing PO
files, updates the repository POT, and refreshes its translation index. Native
new-language creation uses that updated template. Weblate also owns Git sync;
configure its push URL and credentials separately. No custom Peblate source API,
format, database template, or importer is required.

Use a dedicated Weblate account restricted to the component, with source-upload
permissions. Keep its token in CI secrets. Only successful upstream release jobs
may upload; regular pushes, PRs, and nightlies must not change translation sources.

## Configure release delivery

The replacement firmware workflow prepares the merged POT and calls the native
API after the release job succeeds. Delivery is opt-in:

- Create a GitHub environment named `translations`, restricted to release tags.
- Set environment variable `WEBLATE_SOURCE_URL` to the full HTTPS English source
  upload URL shown above (including its trailing slash).
- Store the dedicated Weblate account token as environment secret `WEBLATE_TOKEN`.
- Set repository variable `WEBLATE_UPLOAD_ENABLED=true` when the service is ready.
- Configure Weblate's Git push access to the translations repository separately.

Uploads share one concurrency group and do not cancel an active import. Immediately
before uploading, CI checks all published `v*` releases and skips any run superseded
by a later publication. This includes prereleases and orders by publication time,
not version number; manually republishing an old version needs operator care.
Temporary HTTP failures receive bounded retries; permanent errors fail the job.
The retained source artifact allows inspection without contacting Weblate.

Hosting and credentials are not configured yet. Native source uploads can be
repeated, but they are not transactional across all catalogs and offer no custom
recovery journal. Check Weblate repository status after a failed merge before
retrying. A successful HTTP response can precede Weblate's background index refresh.

Source updates do not publish language packs. Review and pack publication remain
separate work.

## Local verification

Run `examples/docker/source_import_smoke.py` through `weblate shell`. It uses an
isolated local component to check the native source API, saved translations,
contexts and plurals, repeated uploads, and regional new-language creation.
The running demo's POT contains its existing test strings, not a firmware release.
