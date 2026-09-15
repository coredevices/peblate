"""Use Weblate's component and language-scoped permissions for Peblate actions."""

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

from .weblate_adapter import component, translation_for_code


def capabilities(user, translation):
    accessible = (
        user.is_authenticated
        and user.is_active
        and user.can_access_component(translation.component)
    )
    if not accessible or translation.is_source:
        return {"preview": False, "upload": False, "validate": False}
    preview = bool(user.has_perm("translation.download", translation))
    edit = bool(user.has_perm("unit.edit", translation))
    return {
        "preview": preview,
        "upload": preview
        and edit
        and bool(user.has_perm("upload.perform", translation)),
        "validate": preview and edit,
    }


def require_capability(action=None):
    def decorate(view):
        @login_required
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if action is None:
                allowed = request.user.is_active and request.user.can_access_component(
                    component()
                )
            else:
                translation = translation_for_code(kwargs["code"])
                allowed = capabilities(request.user, translation)[action]
            if not allowed:
                raise PermissionDenied(
                    "Your Weblate permissions do not allow this action for this language."
                )
            return view(request, *args, **kwargs)

        return wrapped

    return decorate
