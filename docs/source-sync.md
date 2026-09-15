# Source-string synchronization draft

This integration is not enabled and requires no hosted instance yet. The firmware
side prepares a `translation-source` CI artifact only after a successful `v*`
release. Regular pushes, PRs and nightly builds do not update translation sources. The current local Weblate demo
continues using its existing source catalog; this draft does not replace it.

## Ownership

- **PebbleOS CI:** extract and merge the normal firmware board catalogs, normalize
  volatile headers, and provide the POT plus its hash and firmware revision.
- **Weblate configuration:** dedicated component-scoped CI account, source-update
  permissions, HTTPS endpoint, and repository synchronization settings.
- **Peblate:** receive and retain the latest source snapshot in service storage,
  coordinate merges and new-language creation, and report import status.
- **pebbleos-translations:** updated regional PO catalogs and existing fonts/maps.
  No checked-in POT, service code, or firmware dependency.

Only the POT is uploaded. Revision and SHA-256 travel as request metadata; built-in
font coverage remains the versioned coverage data already used by the tools.

## Why the stock endpoint is not enough yet

Weblate 2026.9.1 offers `method=source` on the translation file upload API. Its
`Translation.handle_source` merges every non-source catalog and, when `new_base`
is configured, replaces that file in the component checkout. The local example
uses `new_base=source.pot`. That would violate the intended repository boundary.

Setting `new_base` to an empty string avoids that file write, but native PO
language creation requires a base file. Therefore, do not enable the native upload
against this demo or simply clear its template setting. Do not monkey-patch
Weblate or temporarily swap component settings around a request.

The next implementation should establish a narrow supported extension for
new-language creation from a service-owned POT. Evaluate a registered PO format
extension's language-creation hook against the pinned Weblate version. If the
necessary context cannot be supplied cleanly, propose an upstream hook before
introducing a broad override. The existing native source-merge operation can be
reused only after its commit, failure, and retry behavior is verified for that
configuration.

API reference: [Weblate 2026.9.1](https://docs.weblate.org/en/weblate-2026.9.1/api.html).

## Proposed receiver contract (not implemented)

1. Authenticate a dedicated CI account and check access to the configured component.
2. Accept one bounded UTF-8 POT and verify its SHA-256, syntax, contexts, plurals,
   format flags, and absence of translated text before touching catalogs.
3. Retain the immutable input in service storage. Persist its firmware revision,
   hash, actor and import status. Identical successful content is a no-op.
4. Serialize imports per component on existing Weblate workers. Reject an older
   revision using verified source history or an agreed monotonic CI delivery
   sequence; hashes alone do not establish ordering.
5. Flush saved translations, merge all regional catalogs under the repository
   lock, and commit only changed PO files. Preserve translations for unchanged
   messages; obsolete removed messages and flag changed matches for review.
6. Promote the new service-owned template only after every merge and repository
   update succeeds. New languages use that same template and the configured
   regional locale naming. Failures retain the previous template and allow retry.
7. Existing pack jobs keep their captured inputs. Imports and new snapshots use
   the same repository lock so readers cannot capture a partial merge.

Before enabling uploads, test an added string, removed string, changed context,
plural change, saved translator edits, duplicate request, stale revision,
concurrent pack build, merge failure, service restart, and new-language creation.
Verify that no font/map changes or POT files enter Git. Include the latest source
snapshot and import receipts in the deployment's backup/restore procedure.

## Hosting activation, later

The firmware draft has **no network upload step**. Add it only after the receiver
and tests above exist. Require an explicit enable variable, a protected deployment
environment, HTTPS URL and scoped token. Restrict delivery to successful releases from the upstream `v*` tag workflow;
regular pushes, nightlies, PRs and forks must not deliver sources.
A failed delivery must fail visibly and be safe to rerun. Pack publication is a
separate operation and is not authorized by importing source strings.
