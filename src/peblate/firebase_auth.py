"""Firebase identity verification through Weblate's native social-auth pipeline.

This initial rollout only links and signs in existing, allowlisted accounts.
It cannot provision users, even when global registration is enabled.
"""

import secrets
import time
from functools import lru_cache

import requests
from django.conf import settings
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.crypto import constant_time_compare
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request
from google.oauth2.id_token import verify_firebase_token
from social_core.backends.base import BaseAuth

STATE_KEY = "peblate_firebase_login"
FLOW_LIFETIME = 600


class PebbleLoginDenied(Exception):
    """A safe, user-facing denial, never containing token data."""


def allowed_emails():
    return {
        email.casefold()
        for email in getattr(settings, "PEBLATE_FIREBASE_TEST_EMAILS", ())
    }


def enabled():
    return bool(
        getattr(settings, "PEBLATE_FIREBASE_ENABLED", False)
        and getattr(settings, "PEBLATE_FIREBASE_PROJECT_ID", "")
        and getattr(settings, "PEBLATE_FIREBASE_API_KEY", "")
        and getattr(settings, "PEBLATE_FIREBASE_AUTH_DOMAIN", "")
        and allowed_emails()
    )


class CertificateRequest(Request):
    def __call__(self, *args, **kwargs):
        # Bound certificate fetches rather than using google-auth's 120s default.
        kwargs["timeout"] = 10
        return super().__call__(*args, **kwargs)


@lru_cache(maxsize=1)
def certificate_request():
    # CacheControl respects Google's public certificate cache headers/rotation.
    from cachecontrol import CacheControl

    return CertificateRequest(session=CacheControl(requests.Session()))


def validate_principal(response):
    now = time.time()
    if not enabled():
        raise PebbleLoginDenied("Pebble sign-in is not available yet.")
    if (
        response.get("email_verified") is not True
        or not isinstance(response.get("email"), str)
        or response["email"].casefold() not in allowed_emails()
    ):
        raise PebbleLoginDenied(
            "Pebble sign-in is limited to invited testers with a verified email."
        )
    project = settings.PEBLATE_FIREBASE_PROJECT_ID
    if (
        response.get("iss") != f"https://securetoken.google.com/{project}"
        or response.get("aud") != project
        or not isinstance(response.get("sub"), str)
        or not 1 <= len(response["sub"]) <= 128
        or not isinstance(response.get("exp"), (int, float))
        or response["exp"] <= now
        or not isinstance(response.get("auth_time"), (int, float))
        or not 0 <= now - response["auth_time"] <= FLOW_LIFETIME
    ):
        raise PebbleLoginDenied("Your sign-in expired. Please start again.")


def existing_account_only(strategy, response, user=None, social=None, **kwargs):
    validate_principal(response)
    if user is None:
        raise PebbleLoginDenied(
            "First sign in to your existing Weblate account, then open "
            "Settings → Account and connect your Pebble account. "
            "New accounts are not enabled yet."
        )
    if not user.is_active or user.email.casefold() != response["email"].casefold():
        raise PebbleLoginDenied(
            "Use the Pebble account with the same email as your Weblate account."
        )
    if social is None and (
        not strategy.request.user.is_authenticated
        or strategy.request.user.pk != user.pk
    ):
        raise PebbleLoginDenied("Sign in to Weblate before linking a Pebble account.")


class PebbleAuth(BaseAuth):
    name = "pebble"
    ID_KEY = "sub"

    def uses_redirect(self):
        return False

    def auth_html(self):
        request = self.strategy.request
        request.peblate_firebase_page = True
        state = secrets.token_urlsafe(32)
        request.session[STATE_KEY] = {
            "state": state,
            "created": time.time(),
            "user": request.user.pk,
        }
        return render_to_string(
            "pebble/login.html",
            {
                "title": "Sign in with Pebble",
                "available": enabled(),
                "state": state,
                "complete_url": reverse("social:complete", args=(self.name,)),
                "firebase_config": {
                    "apiKey": getattr(settings, "PEBLATE_FIREBASE_API_KEY", ""),
                    "authDomain": getattr(settings, "PEBLATE_FIREBASE_AUTH_DOMAIN", ""),
                    "projectId": getattr(settings, "PEBLATE_FIREBASE_PROJECT_ID", ""),
                },
            },
            request=request,
        )

    def auth_complete(self, *args, **kwargs):
        request = self.strategy.request
        flow = request.session.pop(STATE_KEY, None)
        if (
            request.method != "POST"
            or not flow
            or not constant_time_compare(request.POST.get("state", ""), flow["state"])
            or not 0 <= time.time() - flow["created"] <= FLOW_LIFETIME
            or flow["user"] != request.user.pk
        ):
            raise PebbleLoginDenied("Your sign-in session expired. Please start again.")
        if not enabled():
            raise PebbleLoginDenied("Pebble sign-in is not available yet.")
        token = getattr(request, "peblate_id_token", "")
        if not token or len(token) > 16384:
            raise PebbleLoginDenied("No valid Pebble sign-in was received.")
        try:
            decoded = verify_firebase_token(
                token,
                certificate_request(),
                audience=settings.PEBLATE_FIREBASE_PROJECT_ID,
            )
        except (ValueError, TypeError, GoogleAuthError, requests.RequestException):
            raise PebbleLoginDenied(
                "We could not verify your Pebble sign-in. Please try again."
            ) from None
        # Store only verified identity claims in partial pipelines, never tokens.
        response = {
            key: decoded.get(key)
            for key in (
                "sub",
                "email",
                "email_verified",
                "name",
                "iss",
                "aud",
                "exp",
                "auth_time",
            )
        }
        validate_principal(response)
        kwargs.update(response=response, backend=self)
        return self.strategy.authenticate(*args, **kwargs)

    def continue_pipeline(self, partial):
        # Recheck the trial gate when resuming password confirmation or 2FA.
        validate_principal(partial.kwargs.get("response", {}))
        return super().continue_pipeline(partial)

    def get_user_details(self, response):
        return {"email": response["email"], "fullname": response.get("name") or ""}

    def get_user(self, user_id):
        user = super().get_user(user_id)
        if (
            not enabled()
            or not user
            or not user.is_active
            or user.email.casefold() not in allowed_emails()
        ):
            return None
        return user
