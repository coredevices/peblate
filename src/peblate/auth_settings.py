"""Pebble-only signup and opt-in Pebble Accounts authentication."""

import os


def configure_pebble_auth(namespace):
    """Call at the end of Weblate settings; defaults admit nobody."""
    namespace["PEBLATE_FIREBASE_ENABLED"] = (
        os.environ.get("PEBLATE_FIREBASE_ENABLED", "0") == "1"
    )
    for key in ("PROJECT_ID", "API_KEY", "AUTH_DOMAIN"):
        namespace[f"PEBLATE_FIREBASE_{key}"] = os.environ.get(
            f"PEBLATE_FIREBASE_{key}", ""
        )
    # A backend allowlist restricts the UI, but invitations bypass that native
    # filter. Also guard the actual creation step, including email/reset flows.
    namespace["REGISTRATION_ALLOW_BACKENDS"] = ("pebble",)
    pipeline = list(namespace["SOCIAL_AUTH_PIPELINE"])
    if "peblate.firebase_auth.registration_policy" not in pipeline:
        pipeline.insert(
            pipeline.index("social_core.pipeline.user.create_user"),
            "peblate.firebase_auth.registration_policy",
        )
    namespace["SOCIAL_AUTH_PIPELINE"] = tuple(pipeline)
    if not namespace["PEBLATE_FIREBASE_ENABLED"]:
        return
    namespace["AUTHENTICATION_BACKENDS"] = (
        *namespace["AUTHENTICATION_BACKENDS"],
        "peblate.firebase_auth.PebbleAuth",
    )
    namespace["SOCIAL_AUTH_PEBBLE_TITLE"] = "Pebble account"
    namespace["SOCIAL_AUTH_PEBBLE_FORCE_EMAIL_VALIDATION"] = False
    namespace["MIDDLEWARE"] = tuple(
        "peblate.auth_middleware.PebbleSecurityMiddleware"
        if item == "weblate.middleware.SecurityMiddleware"
        else item
        for item in namespace["MIDDLEWARE"]
    )
    # Keep native Weblate linking, audit, reauthentication and 2FA. Never infer
    # account ownership from an email match, even if global settings permit it.
    pipeline = list(namespace["SOCIAL_AUTH_PIPELINE"])
    pipeline.remove("social_core.pipeline.social_auth.associate_by_email")
    pipeline.insert(
        pipeline.index("weblate.accounts.pipeline.store_params"),
        "peblate.firebase_auth.existing_account_only",
    )
    namespace["SOCIAL_AUTH_PEBBLE_PIPELINE"] = tuple(pipeline)
