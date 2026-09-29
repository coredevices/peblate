"""Initial uploads, owner replacements, and language-scoped reviewer overrides.

Call these helpers with the repository lock held so permission checks and writes
see the same assignments. Ownership never comes from submitted or Git metadata.
"""

import hashlib
import json

from pebble_language_tools.lang_commands import resolve_font_entries

from .models import FontOwnership
from .permissions import capabilities


def fingerprint(store, catalog, entry, cache):
    files = {}
    for key in ("file", "license", "characterList"):
        if entry.get(key):
            path = store.resource(catalog, entry[key])
            if path not in cache:
                cache[path] = hashlib.sha256(path.read_bytes()).hexdigest()
            files[key] = cache[path]
    return hashlib.sha256(
        json.dumps([entry, files], sort_keys=True).encode()
    ).hexdigest()


def font_access(user, translation, store, catalog, mapping):
    entries = resolve_font_entries(mapping)
    can_upload = capabilities(user, translation)["upload"]
    reviewer = can_upload and (
        user.is_superuser or user.has_perm("unit.review", translation)
    )
    owned = (
        {
            record.slot: record.fingerprint
            for record in FontOwnership.objects.filter(
                translation=translation, owner=user
            )
        }
        if can_upload and not reviewer
        else {}
    )
    cache = {}
    allowed = {}
    for slot, entry in entries.items():
        if not can_upload:
            allowed[slot] = False
        elif reviewer or not entry.get("file"):
            allowed[slot] = True
        elif slot in owned:
            try:
                allowed[slot] = owned[slot] == fingerprint(store, catalog, entry, cache)
            except (OSError, ValueError):
                allowed[slot] = False
        else:
            allowed[slot] = False
    # Replacing a source slot also changes aliases pointing at it. A contributor
    # must have permission for every affected style, not just the posted slot.
    return entries, {
        slot: allowed[slot]
        and all(
            allowed[name] for name, entry in entries.items() if entry["name"] == slot
        )
        for slot in entries
    }


def affected_slots(mapping, slot):
    return {slot} | {
        name
        for name, entry in resolve_font_entries(mapping).items()
        if entry["name"] == slot
    }


def record_ownership(user, translation, store, catalog, mapping, slots):
    entries = resolve_font_entries(mapping)
    cache = {}
    for slot in slots:
        entry = entries[slot]
        if entry.get("file"):
            value = fingerprint(store, catalog, entry, cache)
            record, created = FontOwnership.objects.get_or_create(
                translation=translation,
                slot=slot,
                defaults={
                    "owner": user,
                    "fingerprint": value,
                },
            )
            if not created and record.fingerprint != value:
                record.owner = user
                record.fingerprint = value
                record.save(update_fields=["owner", "fingerprint"])
