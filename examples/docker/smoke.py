# SPDX-FileCopyrightText: 2026 Core Devices LLC
# SPDX-License-Identifier: Apache-2.0

"""Test the installed extension using disposable font storage and local demo catalogs."""

import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.test import Client, override_settings
from weblate.trans.models import Component
from weblate.vcs.git import LocalRepository

from peblate import views
from peblate.asset_store import AssetStore
from peblate.checks import configuration_checks
from peblate.models import LanguageJob
from peblate.tasks import run_language_job
from peblate.views import asset_path, mapping_for

asset_temp = tempfile.TemporaryDirectory(prefix="peblate-test-")
views.CACHE_ROOT = Path(asset_temp.name) / "cache"
owner = Component.objects.get(project__slug="pebbleos", slug="watch")
assert owner.vcs == "local" and owner.repo == "local:"
repo_path = Path(asset_temp.name) / "repository"
with owner.repository.lock:
    subprocess.run(
        ["git", "clone", "--no-local", owner.full_path, str(repo_path)],
        check=True,
        capture_output=True,
    )
for args in (
    ["remote", "remove", "origin"],
    ["config", "user.name", "Peblate test"],
    ["config", "user.email", "test@localhost"],
):
    subprocess.run(
        ["git", "-C", str(repo_path), *args], check=True, capture_output=True
    )
repository = LocalRepository(str(repo_path), local=True)


def git(args):
    return repository.execute(args, remote_op="none")


store = AssetStore(repo_path, git, repository.lock)


def test_language_store(code):
    translation = owner.translation_set.get(
        Q(language__code=code) | Q(language_code=code)
    )
    return store, Path(translation.filename)


store_patch = patch("peblate.views.language_store", test_language_store)
store_patch.start()


def run_job(client, path, data):
    with patch("peblate.job_views.run_language_job.apply_async"):
        response = client.post(path, {**data, "format": "json"})
    assert response.status_code == 202, response.content[:500]
    job = response.json()
    with (
        patch("peblate.tasks.language_store", test_language_store),
        override_settings(PEBLATE_CACHE_ROOT=str(views.CACHE_ROOT)),
    ):
        run_language_job.run(job["id"])
        result = client.get(job["status_url"]).json()
        assert result["status"] == "succeeded", result
        if result["download_url"]:
            download = client.get(result["download_url"])
            response = HttpResponse(
                b"".join(download.streaming_content),
                headers={"Content-Disposition": download["Content-Disposition"]},
            )
        else:
            response = JsonResponse(result["report"])
            response.json = lambda: result["report"]
    LanguageJob.objects.filter(pk=job["id"]).delete()
    return response


assert views.font_assignment("fr", {"name": "GOTHIC_14_EXTENDED", "file": ""}) == {
    "font_name": None,
    "license_name": None,
}
client = Client()
assert client.get("/pebble/").status_code == 302
client.force_login(get_user_model().objects.get(username="admin"))
for path in ("/pebble/", "/pebble/fr/", "/pebble/he_IL/"):
    response = client.get(path)
    assert response.status_code == 302, (path, response.status_code)
    assert response.url.startswith(("/translate/", "/projects/")), response.url
for path in (
    "/translate/pebbleos/watch/fr/",
    "/translate/pebbleos/watch/he_IL/",
    "/new-lang/pebbleos/watch/",
):
    response = client.get(path)
    assert response.status_code == 200, (path, response.status_code)
    if path.startswith("/translate/"):
        assert b'id="pebble-editor-panel-template"' in response.content
    print(path, response.status_code)
response = run_job(client, "/pebble/fr/validate/", {"format": "json"})
assert response.status_code == 200, response.content[:500]
assert response.json()["ok"], response.json()
print("French validation:", response.json()["progress"])
with Path("/prototype/hebrew-fonts/Heebo-Regular.ttf").open("rb") as font:
    response = client.post(
        "/pebble/he_IL/font/",
        {
            "slot": "GOTHIC_18_EXTENDED",
            "font": font,
            "format": "json",
            "license": SimpleUploadedFile(
                "LICENSE.txt",
                Path("/prototype/hebrew-fonts/LICENSE.Heebo.txt").read_bytes(),
            ),
        },
    )
assert response.status_code == 200, response.content[:500]
assert response.json()["slot"] == "GOTHIC_18_EXTENDED"
assert client.get(response.json()["font_url"]).status_code == 200
response = run_job(client, "/pebble/he_IL/validate/", {"format": "json"})
assert response.status_code == 200, response.content[:500]
report = response.json()
assert report["ok"], report
slot = next(font for font in report["fonts"] if font["slot"] == "GOTHIC_18_EXTENDED")
assert slot["uncovered_characters"] == [], slot
print("Uploaded Hebrew font: coverage passed for body text")
response = run_job(client, "/pebble/he_IL/validate/", {"action": "build"})
assert response.status_code == 200, response.content[:500]
assert response["Content-Disposition"] == 'attachment; filename="he_IL.pbl"'
assert response.content[:4] == b"\x15\0\0\0"
print("Built Hebrew pack:", len(response.content), "bytes")
component = Component.objects.get(project__slug="pebbleos", slug="watch")
assert component.vcs == "local" and component.repo == "local:"
print("Local repository only; no upstream publishing configured")

# Missing licenses must not change the existing mapping.
before = mapping_for("he_IL")
with Path("/prototype/hebrew-fonts/Heebo-Regular.ttf").open("rb") as font:
    response = client.post(
        "/pebble/he_IL/font/", {"slot": "GOTHIC_18_EXTENDED", "font": font}
    )
assert response.status_code == 400
assert mapping_for("he_IL") == before
for slot_name in ("GOTHIC_18_EXTENDED", "GOTHIC_24_EXTENDED"):
    with Path("/prototype/hebrew-fonts/Heebo-Regular.ttf").open("rb") as font:
        response = client.post(
            "/pebble/he_IL/font/",
            {
                "slot": slot_name,
                "font": font,
                "format": "json",
                "license": SimpleUploadedFile(
                    "LICENSE.txt",
                    Path("/prototype/hebrew-fonts/LICENSE.Heebo.txt").read_bytes(),
                ),
            },
        )
    assert response.status_code == 200, response.content[:500]
entries = mapping_for("he_IL")["fonts"]
a = next(entry for entry in entries if entry["name"] == "GOTHIC_18_EXTENDED")
b = next(entry for entry in entries if entry["name"] == "GOTHIC_24_EXTENDED")
assert a["file"] == b["file"] and a["license"] == b["license"]
assert asset_path("he_IL", a) == asset_path("he_IL", b)
assert asset_path("he_IL", a, "license") == asset_path("he_IL", b, "license")
with store.lock:
    assert git(["status", "--porcelain"]).strip() == ""
    assert git(["remote"]).strip() == ""
response = client.post(
    "/pebble/he_IL/font/GOTHIC_18_EXTENDED/pbf/", {"text": "שלום Hello"}
)
assert response.status_code == 200, response.content[:500]
assert response.content[0] & 15 == 3
Path("/app/data/preview-he.pbf").write_bytes(response.content)
print(
    "License required; repeated uploads deduplicated; extension PBF compiled",
    len(response.content),
)
assert "/site-packages/peblate/" in str(Path(views.__file__))
assert Path(finders.find("pebble/renderer/renderer.js")).is_file()
assert Path(finders.find("pebble/renderer/GOTHIC_18.pbf")).is_file()
client = Client()
assert client.post("/pebble/he_IL/font/").status_code == 302
client.force_login(get_user_model().objects.get(username="admin"))
with override_settings(PEBLATE_COMPONENT="absent/component"):
    assert client.get("/pebble/he_IL/").status_code == 404
    response = client.get("/translate/pebbleos/watch/he_IL/")
    assert b'id="pebble-editor-panel-template"' not in response.content
with override_settings(PEBLATE_COMPONENT="", PEBLATE_CACHE_ROOT=None):
    assert {e.id for e in configuration_checks(None)} >= {
        "peblate.E001",
        "peblate.E002",
    }
print(
    "Installed extension, renderer assets, component configuration and auth checks passed"
)
# A separate clone has no service cache, hard links, or uncommitted files.
clone = Path(asset_temp.name) / "fresh-clone"
subprocess.run(
    ["git", "clone", "--no-local", str(repo_path), str(clone)],
    check=True,
    capture_output=True,
)
output = Path(asset_temp.name) / "packs"
subprocess.run(
    [
        sys.executable,
        "-m",
        "pebble_language_tools.lang",
        "--root",
        str(clone),
        "pack_lang",
        "--lang",
        "he_IL",
        "--output",
        str(output),
    ],
    check=True,
)
response = run_job(client, "/pebble/he_IL/validate/", {"action": "build"})
assert response.status_code == 200
assert response.content == (output / "he_IL.pbl").read_bytes()
assert not list(clone.rglob("*.pbf"))
print(
    "Fresh Git clone builds byte-identical Hebrew pack; no generated fonts or upstream remote in test repository"
)
store_patch.stop()
asset_temp.cleanup()
