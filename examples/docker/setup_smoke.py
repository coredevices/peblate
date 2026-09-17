# SPDX-FileCopyrightText: 2026 Core Devices LLC
# SPDX-License-Identifier: Apache-2.0

"""Verify pre-creation coverage and native creation permissions."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.test import Client, RequestFactory
from django.test.utils import override_settings

from peblate.weblate_adapter import component

owner = component()
before = owner.translation_set.count()
for username, allowed in [
    ("admin", True),
    ("peblate-translator", True),
    ("peblate-viewer", False),
    ("peblate-outsider", False),
]:
    client = Client()
    client.force_login(get_user_model().objects.get(username=username))
    entry = client.get("/new-lang/pebbleos/")
    if allowed:
        assert entry.status_code == 302 and entry.url == "/new-lang/pebbleos/watch/", (
            username
        )
    else:
        assert entry.status_code in (302, 403, 404), username
        assert getattr(entry, "url", None) != "/new-lang/pebbleos/watch/", username
    page = client.get("/new-lang/pebbleos/watch/")
    assert (b'id="pebble-language-setup"' in page.content) == allowed, username
    response = client.get("/pebble/setup/coverage/", {"language": "fr"})
    assert response.status_code == (200 if allowed else 403), (
        username,
        response.status_code,
    )
    if allowed:
        assert response.json()["known"] and not response.json()["styles"]
        response = client.get("/pebble/setup/coverage/", {"language": "ar"})
        assert response.json()["known"] and response.json()["styles"]
        assert (
            client.get(
                "/pebble/setup/coverage/", {"language": "not-a-language"}
            ).status_code
            == 404
        )
assert Client().get("/pebble/setup/coverage/", {"language": "ar"}).status_code == 302
assert owner.translation_set.count() == before
print(
    "PASS: native form, French/Arabic guidance, access controls, invalid languages, no creation during review"
)

# Unknown projects retain native 404 behavior; anonymous users retain native login.
assert client.get("/new-lang/absent-project/").status_code == 404
assert Client().get("/new-lang/pebbleos/").status_code == 302
print("PASS: project entry redirects to setup with native access checks")

# Preserve native submissions and multi-component/other-project behavior.
from peblate.weblate_adapter import project_language_setup

factory = RequestFactory()
admin = get_user_model().objects.get(username="admin")
with patch(
    "weblate.trans.views.basic.new_language", return_value=HttpResponse("native")
) as native:
    request = factory.post("/new-lang/pebbleos/", {"lang": "fr"})
    request.user = admin
    assert project_language_setup(request, "pebbleos").content == b"native"
    native.assert_called_once_with(request, path=["pebbleos"])
    request = factory.get("/new-lang/pebbleos/")
    request.user = admin
    with override_settings(PEBLATE_COMPONENT="another/watch"):
        assert project_language_setup(request, "pebbleos").content == b"native"
    with patch.object(
        type(owner.project),
        "components_user_can_add_new_language",
        return_value=[owner, object()],
    ):
        assert project_language_setup(request, "pebbleos").content == b"native"
print("PASS: native POST, other projects and multi-component flow preserved")
