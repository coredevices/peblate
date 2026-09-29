from django.apps import AppConfig


class PeblateConfig(AppConfig):
    name = "peblate"
    verbose_name = "Peblate"

    def ready(self):
        from weblate.trans.signals import translation_post_add

        from . import checks  # noqa: F401
        from .setup_views import install_creation_fonts

        translation_post_add.connect(
            install_creation_fonts, dispatch_uid="peblate-setup-fonts"
        )
