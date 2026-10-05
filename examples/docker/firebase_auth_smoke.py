"""Real JWT verification and native account linking, on local disposable users.

Run with `weblate shell < firebase_auth_smoke.py`. No Firebase accounts or
messages are created. The database transaction is rolled back after the test.
"""

import json
import os
import re
import time
import uuid
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import Client, override_settings
from django_otp.plugins.otp_totp.models import TOTPDevice
from social_core.exceptions import AuthForbidden
from social_django.models import Partial, UserSocialAuth

from peblate.auth_settings import configure_pebble_auth
from peblate.firebase_auth import STATE_KEY, registration_policy

assert settings.SITE_DOMAIN == "localhost:8088", "Run only in the local prototype"
User = get_user_model()
suffix = uuid.uuid4().hex[:12]
email = f"pebble-{suffix}@example.com"
password = f"Local-auth-test-{suffix}!"
namespace = {
    "AUTHENTICATION_BACKENDS": tuple(
        item for item in settings.AUTHENTICATION_BACKENDS if "PebbleAuth" not in item
    ),
    "SOCIAL_AUTH_PIPELINE": settings.SOCIAL_AUTH_PIPELINE,
    "MIDDLEWARE": settings.MIDDLEWARE,
}
with patch.dict(
    os.environ,
    {
        "PEBLATE_FIREBASE_ENABLED": "1",
        "PEBLATE_FIREBASE_PROJECT_ID": "peblate-auth-test",
        "PEBLATE_FIREBASE_API_KEY": "public-test-key",
        "PEBLATE_FIREBASE_AUTH_DOMAIN": "peblate-auth-test.firebaseapp.com",
        # Stale deployment allowlists must not restrict existing users.
        "PEBLATE_FIREBASE_TEST_EMAILS": "former-tester@example.org",
    },
):
    configure_pebble_auth(namespace)

key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
public_key = (
    key.public_key()
    .public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    .decode()
)


class CertificateResponse:
    status = 200
    data = json.dumps({"test-key": public_key}).encode()


def transport(*args, **kwargs):
    return CertificateResponse()


def token(**changes):
    now = int(time.time())
    claims = {
        "sub": f"firebase-{suffix}",
        "email": email,
        "email_verified": True,
        "name": "Pebble login tester",
        "aud": "peblate-auth-test",
        "iss": "https://securetoken.google.com/peblate-auth-test",
        "iat": now,
        "exp": now + 3600,
        "auth_time": now,
    }
    claims.update(changes)
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test-key"})


def begin(client):
    page = client.get("/accounts/profile/", follow=True)
    if b'name="csrfmiddlewaretoken"' not in page.content:
        page = client.get("/accounts/login/existing/")
    client.pebble_csrf = re.search(
        r'name="csrfmiddlewaretoken" value="([^"]+)"', page.content.decode()
    )[1]
    response = client.post(
        "/accounts/login/pebble/",
        {
            "csrfmiddlewaretoken": client.pebble_csrf,
            "next": "/accounts/profile/#account",
        },
    )
    assert response.status_code == 200, (response.status_code, response.content[:600])
    assert b"Sign in with Pebble" in response.content
    if settings.PEBLATE_FIREBASE_ENABLED:
        assert (
            "https://www.gstatic.com/firebasejs/10.12.2/"
            in response["Content-Security-Policy"]
        )
        assert (
            "https://peblate-auth-test.firebaseapp.com"
            in response["Content-Security-Policy"]
        )
        assert (
            "'unsafe-inline'"
            not in response["Content-Security-Policy"]
            .split("script-src")[1]
            .split(";")[0]
        )
    client.pebble_csrf = (
        re.search(
            r'name="csrfmiddlewaretoken" value="([^"]+)"', response.content.decode()
        )[1]
        if b'name="csrfmiddlewaretoken"' in response.content
        else client.pebble_csrf
    )
    return client.session[STATE_KEY]["state"]


def complete(client, proof=None, state=None):
    state = begin(client) if state is None else state
    return client.post(
        "/accounts/complete/pebble/",
        {
            "csrfmiddlewaretoken": client.pebble_csrf,
            "id_token": proof or token(),
            "state": state,
        },
    )


with (
    transaction.atomic(),
    override_settings(
        **namespace,
        REGISTRATION_OPEN=False,
        EMAIL_BACKEND="django.core.mail.backends.dummy.EmailBackend",
    ),
    patch("peblate.firebase_auth.certificate_request", return_value=transport),
    patch("peblate.auth_views.check_rate_limit", return_value=True),
    patch("celery.app.task.Task.apply_async"),
):
    user = User.objects.create_user(
        username=f"pebble-auth-{suffix}",
        email=email,
        password=password,
    )
    other = User.objects.create_user(
        username=f"pebble-other-{suffix}",
        email=f"other-{email}",
        password=password,
    )
    count = User.objects.count()
    original_groups = set(user.groups.values_list("pk", flat=True))
    public = Client(enforce_csrf_checks=True)
    assert (
        "www.gstatic.com/firebasejs"
        not in public.get("/accounts/login/")["Content-Security-Policy"]
    )
    entry = public.get("/accounts/login/", {"next": "/pebble/"})
    assert entry.status_code == 200 and b"/accounts/login/pebble/" in entry.content
    assert b'name="username"' not in entry.content
    # Refreshing the provider page restarts via the protected POST entry.
    refresh = public.get("/accounts/login/pebble/", {"next": "/pebble/"})
    assert (
        refresh.status_code == 302
        and refresh.url == "/accounts/login/?next=%2Fpebble%2F"
    )
    begin(public)
    provider = public.post(
        "/accounts/login/pebble/",
        {"csrfmiddlewaretoken": public.pebble_csrf, "next": "/pebble/"},
    )
    assert b"Continue with Google" in provider.content
    assert b"Continue with Apple" in provider.content
    assert b"Continue with GitHub" in provider.content
    assert b"Account settings</a>" not in provider.content
    assert b"/accounts/login/existing/?next=/pebble/" in provider.content
    assert b'name="username"' not in provider.content
    password_client = Client(enforce_csrf_checks=True)
    password_page = password_client.get("/accounts/login/existing/")
    assert b'name="username"' in password_page.content
    assert b'name="password"' in password_page.content
    assert b"Continue with Google" not in password_page.content
    password_csrf = re.search(
        r'name="csrfmiddlewaretoken" value="([^"]+)"', password_page.content.decode()
    )[1]
    bad_password = password_client.post(
        "/accounts/login/existing/",
        {
            "username": user.username,
            "password": "incorrect",
            "csrfmiddlewaretoken": password_csrf,
        },
    )
    assert (
        bad_password.status_code == 200
        and "_auth_user_id" not in password_client.session
    )
    password_csrf = re.search(
        r'name="csrfmiddlewaretoken" value="([^"]+)"', bad_password.content.decode()
    )[1]
    password_login = password_client.post(
        "/accounts/login/existing/",
        {
            "username": user.username,
            "password": password,
            "csrfmiddlewaretoken": password_csrf,
            "next": "/pebble/",
        },
    )
    assert password_login.status_code == 302 and password_login.url == "/pebble/"
    assert password_client.session["_auth_user_id"] == str(user.pk)

    # Any valid identity must explicitly link an existing account first.
    response = complete(public)
    assert response.status_code == 403 and b"First sign in" in response.content
    for registration_open in (False, True):
        with override_settings(REGISTRATION_OPEN=registration_open):
            assert complete(public).status_code == 403
            if not registration_open:
                response = complete(
                    public, token(sub=f"unknown-{suffix}", email="new-user@example.org")
                )
                assert (
                    response.status_code == 403 and b"not enabled" in response.content
                )
            assert User.objects.count() == count
    assert User.objects.count() == count
    assert namespace["REGISTRATION_ALLOW_BACKENDS"] == ("pebble",)
    assert (
        public.post(
            "/accounts/register/",
            {
                "email": "new-user@example.org",
                "csrfmiddlewaretoken": public.pebble_csrf,
            },
        ).status_code
        == 403
    )

    for changes in (
        {"email_verified": False},
        {"email_verified": "true"},
        {"email": None},
        {"email": ""},
        {"email": " "},
        {"aud": "another-project"},
        {"iss": "https://securetoken.google.com/another-project"},
        {"exp": int(time.time()) - 10},
        {"exp": "invalid"},
        {"auth_time": int(time.time()) - 700},
        {"auth_time": int(time.time()) + 100},
        {"sub": ""},
    ):
        response = complete(public, token(**changes))
        assert response.status_code == 403, (changes, response.status_code)
        assert "_auth_user_id" not in public.session
    bad_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forged = jwt.encode(
        jwt.decode(token(), options={"verify_signature": False}),
        bad_key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )
    assert complete(public, forged).status_code == 403
    assert complete(public, "not-a-jwt").status_code == 403
    with patch("peblate.auth_views.check_rate_limit", return_value=False):
        response = complete(public)
        assert response.status_code == 403 and b"Too many" in response.content

    state = begin(public)
    response = public.post(
        "/accounts/complete/pebble/", {"state": state, "id_token": token()}
    )
    assert response.status_code == 403  # No CSRF token.
    assert (
        public.get(
            "/accounts/complete/pebble/", {"state": state, "id_token": token()}
        ).status_code
        == 403
    )
    assert complete(public, state="wrong-state").status_code == 403

    with override_settings(PEBLATE_FIREBASE_ENABLED=False):
        assert complete(public).status_code == 403

    # Linking a different Weblate account cannot merge or acquire privileges.
    wrong = Client(enforce_csrf_checks=True)
    wrong.force_login(other, backend="weblate.accounts.auth.WeblateUserBackend")
    assert complete(wrong).status_code == 403
    assert not UserSocialAuth.objects.filter(provider="pebble", user=other).exists()

    client = Client(enforce_csrf_checks=True)
    assert client.login(username=user.username, password=password)
    response = complete(client)
    assert response.status_code == 302 and response.url == "/accounts/confirm/", (
        response
    )
    assert not UserSocialAuth.objects.filter(provider="pebble", user=user).exists()
    # Native password reauthentication is preserved and raw credentials never
    # enter the stored partial pipeline.
    partial = Partial.objects.filter(backend="pebble").latest("id")
    serialized = json.dumps(partial.data)
    assert "id_token" not in serialized and token() not in serialized
    response = client.post(
        "/accounts/confirm/",
        {
            "csrfmiddlewaretoken": client.pebble_csrf,
            "password": password,
        },
    )
    assert response.status_code == 302, response.content[:500]
    response = client.get(response.url)
    assert response.status_code == 302, response.content[:500]
    association = UserSocialAuth.objects.get(provider="pebble", user=user)
    assert association.uid == f"firebase-{suffix}"
    assert User.objects.count() == count
    user.refresh_from_db()
    assert not user.is_staff and not user.is_superuser
    assert user.check_password(password)
    assert set(user.groups.values_list("pk", flat=True)) == original_groups

    # Returning login reuses the exact same account and honors safe redirects.
    signed_out = Client(enforce_csrf_checks=True)
    state = begin(signed_out)
    proof = token()
    response = complete(signed_out, proof, state)
    assert response.status_code == 302, response.content[:500]
    assert signed_out.session["_auth_user_id"] == str(user.pk)
    assert complete(signed_out, proof, state).status_code == 403  # One-shot flow.
    assert signed_out.get("/accounts/profile/").status_code == 200
    with override_settings(PEBLATE_FIREBASE_ENABLED=False):
        assert signed_out.get("/accounts/profile/").status_code == 302

    # No disabled user login, even for a previously linked Firebase UID.
    user.is_active = False
    user.save(update_fields=["is_active"])
    assert complete(Client(enforce_csrf_checks=True)).status_code == 403
    user.is_active = True
    user.save(update_fields=["is_active"])

    # Native 2FA must run before granting a Firebase session.
    TOTPDevice.objects.create(user=user, name="test", confirmed=True)
    password_2fa = Client(enforce_csrf_checks=True)
    password_page = password_2fa.get("/accounts/login/existing/")
    password_csrf = re.search(
        r'name="csrfmiddlewaretoken" value="([^"]+)"', password_page.content.decode()
    )[1]
    password_response = password_2fa.post(
        "/accounts/login/existing/",
        {
            "username": user.username,
            "password": password,
            "csrfmiddlewaretoken": password_csrf,
        },
    )
    assert (
        password_response.status_code == 302
        and "/auth/second-factor/" in password_response.url
    )
    assert "_auth_user_id" not in password_2fa.session
    two_factor = Client(enforce_csrf_checks=True)
    response = complete(two_factor)
    assert response.status_code == 302 and "/auth/second-factor/" in response.url, (
        response
    )
    assert "_auth_user_id" not in two_factor.session
    assert User.objects.count() == count

    # Ordinary password recovery for existing users remains available with
    # email registration blocked. Mock the delivery so this sends no email.
    reset = Client(enforce_csrf_checks=True)
    with override_settings(REGISTRATION_CAPTCHA=False):
        reset_page = reset.get("/accounts/reset/")
        reset_csrf = re.search(
            r'name="csrfmiddlewaretoken" value="([^"]+)"', reset_page.content.decode()
        )[1]
        with patch(
            "weblate.accounts.views.send_password_reset_email", return_value=None
        ) as delivery:
            reset_response = reset.post(
                "/accounts/reset/",
                {
                    "email": email,
                    "csrfmiddlewaretoken": reset_csrf,
                },
            )
        assert reset_response.status_code == 302 and delivery.called
        assert delivery.call_args.args[1].pk == user.pk
        assert User.objects.count() == count

    # Open registration admits verified Pebble identities only. Native account
    # creation supplies ordinary default teams, an unusable password and audit.
    with override_settings(REGISTRATION_OPEN=True):
        registration_page = public.get("/accounts/register/")
        assert registration_page.status_code == 200
        assert b"/accounts/login/pebble/" in registration_page.content
        assert b'name="email"' not in registration_page.content
        # An invitation session must not expose native email registration.
        invited = Client()
        invited_session = invited.session
        invited_session["invitation_link"] = str(uuid.uuid4())
        invited_session.save()
        invited_page = invited.get("/accounts/register/")
        assert b"/accounts/login/pebble/" in invited_page.content
        assert b'name="email"' not in invited_page.content
        assert (
            public.post(
                "/accounts/register/",
                {
                    "email": "new-user@example.org",
                    "csrfmiddlewaretoken": public.pebble_csrf,
                },
            ).status_code
            == 403
        )
        from types import SimpleNamespace

        # The creation-step guard is global: invitations and password-reset
        # actions cannot let an email or other provider provision a new user.
        for backend_name in ("email", "github", "google-oauth2"):
            try:
                registration_policy(
                    None,
                    SimpleNamespace(name=backend_name),
                    {"email": "new-user@example.org"},
                    invitation_link=object(),
                    weblate_action="reset",
                )
            except AuthForbidden:
                pass
            else:
                raise AssertionError("Alternate backend allowed to create a user")
        signup = Client(enforce_csrf_checks=True)
        new_email = f"new-pebble-{suffix}@example.com"
        new_uid = f"new-firebase-{suffix}"
        for invalid in (
            token(sub=new_uid, email=new_email, email_verified=False),
            token(sub=new_uid, email=new_email, aud="wrong-project"),
            token(sub=new_uid, email=new_email, exp=int(time.time()) - 10),
        ):
            assert complete(signup, invalid).status_code == 403
            assert User.objects.count() == count
        response = complete(
            signup,
            token(sub=new_uid, email=new_email, is_staff=True, is_superuser=True),
        )
        assert response.status_code == 302, (
            response.status_code,
            response.content[:1000],
        )
        created = User.objects.get(email=new_email)
        assert signup.session["_auth_user_id"] == str(created.pk)
        assert not created.is_staff and not created.is_superuser
        assert not created.has_usable_password()
        assert not created.groups.filter(
            roles__permissions__codename="unit.review"
        ).exists()
        association = UserSocialAuth.objects.get(provider="pebble", user=created)
        assert association.uid == new_uid
        assert association.verifiedemail_set.filter(email=new_email).exists()
        assert User.objects.count() == count + 1
        returning = Client(enforce_csrf_checks=True)
        response = complete(returning, token(sub=new_uid, email=new_email))
        assert response.status_code == 302 and returning.session[
            "_auth_user_id"
        ] == str(created.pk)
        assert (
            complete(
                Client(enforce_csrf_checks=True),
                token(sub="different-uid", email=new_email),
            ).status_code
            == 403
        )
        assert User.objects.count() == count + 1
        with override_settings(PEBLATE_FIREBASE_ENABLED=False):
            assert (
                complete(
                    Client(enforce_csrf_checks=True),
                    token(sub="disabled-uid", email="disabled@example.org"),
                ).status_code
                == 403
            )
        with override_settings(REGISTRATION_OPEN=False):
            assert (
                complete(
                    Client(enforce_csrf_checks=True),
                    token(sub="closed-uid", email="closed@example.org"),
                ).status_code
                == 403
            )
        assert User.objects.count() == count + 1
    transaction.set_rollback(True)

print(
    "PASS: signed JWTs, Pebble-only signup, closed-registration gate, CSRF/state, explicit existing-account linking,"
)
print(
    "Pebble-first login, existing password login, password confirmation, no token persistence, same-user login, inactive users and native 2FA"
)
