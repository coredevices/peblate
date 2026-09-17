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


def project_language_setup(request, project):
    """Use guided setup when the project has one eligible Peblate component.

    Delegate other projects, permissions and POSTs to the native view. In projects
    with several eligible components, preserve Weblate's multi-component form.
    """
    from django.shortcuts import redirect
    from django.urls import reverse
    from weblate.trans.views.basic import new_language

    user = request.user
    if (
        request.method == "GET"
        and user.is_authenticated
        and user.is_active
        and enabled_component().split("/")[0] == project
    ):
        owner = component()
        if (
            user.can_access_component(owner)
            and user.has_perm("translation.add", owner)
            and owner.effective_new_lang == "add"
            and owner.can_add_new_language(user)
            and list(owner.project.components_user_can_add_new_language(user))
            == [owner]
        ):
            return redirect(
                reverse("new-language", kwargs={"path": owner.get_url_path()})
            )
    return new_language(request, path=[project])
