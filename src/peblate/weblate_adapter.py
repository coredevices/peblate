"""Version-sensitive Weblate operations, tested against Weblate 2026.9.1.

The corresponding template blocks and selectors live in translate.html and editor.js.
"""

from django.conf import settings
from django.db.models import Q
from django.shortcuts import get_object_or_404
from weblate.trans.models import Component, Translation


def enabled_component():
    return settings.PEBLATE_COMPONENT


def component():
    project, name = enabled_component().split("/")
    return get_object_or_404(Component, project__slug=project, slug=name)


def translation_for_code(code):
    return get_object_or_404(
        Translation,
        Q(language_code=code) | Q(language__code=code),
        component=component(),
    )


def saved_catalog(translation):
    translation.commit_pending("pebble-preview", None, skip_push=True)
    return translation.get_filename()


def language_store(code):
    from pathlib import Path

    from .asset_store import AssetStore

    translation = translation_for_code(code)
    owner = translation.component
    repository = owner.repository

    def git(args):
        result = repository.execute(args, remote_op="none")
        if args[0] == "commit":
            repository.clean_revision_cache()
        return result

    store = AssetStore(owner.full_path, git, repository.lock)
    catalog = Path(translation.get_filename()).relative_to(store.root)
    return store, catalog
