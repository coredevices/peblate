INSTALLED_APPS = ["peblate", *INSTALLED_APPS]  # noqa: F821 - executed in Weblate settings
ROOT_URLCONF = "peblate.urls"
PEBLATE_COMPONENT = "pebbleos/watch"
PEBLATE_CACHE_ROOT = "/app/data/peblate-cache"
# Local example only.
EMAIL_BACKEND = "django.core.mail.backends.dummy.EmailBackend"
