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
from social_django.models import Partial, UserSocialAuth

from peblate.auth_settings import configure_pebble_auth
from peblate.firebase_auth import STATE_KEY

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
        "PEBLATE_FIREBASE_TEST_EMAILS": email,
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
    assert b"invited testers" in response.content
    if settings.PEBLATE_FIREBASE_ENABLED and settings.PEBLATE_FIREBASE_TEST_EMAILS:
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

    # Even a valid invited identity must explicitly link an existing account.
    response = complete(public)
    assert response.status_code == 403 and b"First sign in" in response.content
    with override_settings(REGISTRATION_OPEN=True):
        assert complete(public).status_code == 403
    assert User.objects.count() == count

    for changes in (
        {"email": "outsider@example.com"},
        {"email_verified": False},
        {"email_verified": "true"},
        {"email": None},
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

    with override_settings(PEBLATE_FIREBASE_TEST_EMAILS=()):
        assert complete(public).status_code == 403
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
    with override_settings(PEBLATE_FIREBASE_TEST_EMAILS=()):
        assert signed_out.get("/accounts/profile/").status_code == 302

    # No disabled user login, even for a previously linked Firebase UID.
    user.is_active = False
    user.save(update_fields=["is_active"])
    assert complete(Client(enforce_csrf_checks=True)).status_code == 403
    user.is_active = True
    user.save(update_fields=["is_active"])

    # Native 2FA must run before granting a Firebase session.
    TOTPDevice.objects.create(user=user, name="test", confirmed=True)
    two_factor = Client(enforce_csrf_checks=True)
    response = complete(two_factor)
    assert response.status_code == 302 and "/auth/second-factor/" in response.url, (
        response
    )
    assert "_auth_user_id" not in two_factor.session
    assert User.objects.count() == count
    transaction.set_rollback(True)

print(
    "PASS: signed JWTs, closed allowlist, CSRF/state, explicit existing-account linking,"
)
print(
    "password confirmation, no token persistence, same-user login, inactive users and native 2FA"
)
