from importlib.metadata import version

from django.conf import settings
from django.core.checks import Error, Warning, register


@register()
def configuration_checks(app_configs, **kwargs):
    errors = []
    component = getattr(settings, "PEBLATE_COMPONENT", "")
    if len(component.split("/")) != 2 or not all(component.split("/")):
        errors.append(
            Error("Set PEBLATE_COMPONENT to project/component.", id="peblate.E001")
        )
    if not getattr(settings, "PEBLATE_CACHE_ROOT", None):
        errors.append(
            Error(
                "Set PEBLATE_CACHE_ROOT to a writable preview-cache directory.",
                id="peblate.E002",
            )
        )
    if version("weblate") != "2026.9.1":
        errors.append(
            Warning(
                "Peblate is tested with Weblate 2026.9.1; run integration tests before upgrading.",
                id="peblate.W001",
            )
        )
    return errors
