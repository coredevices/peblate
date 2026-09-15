from django.apps import AppConfig


class PeblateConfig(AppConfig):
    name = "peblate"
    verbose_name = "Peblate"

    def ready(self):
        from . import checks  # noqa: F401
