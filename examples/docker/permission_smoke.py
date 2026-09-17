"""Exercise native Weblate roles and Peblate endpoints in disposable asset storage."""

import json
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models import Q
from django.test import Client
from weblate.vcs.git import LocalRepository

from peblate.asset_store import AssetStore
from peblate.font_guidance import baseline_coverage
from peblate.models import LanguageJob
from peblate.permissions import capabilities
from peblate.weblate_adapter import component, translation_for_code

assert baseline_coverage("en_US")["GOTHIC_18_EXTENDED"] == 0
assert baseline_coverage("fr_FR")["GOTHIC_18_EXTENDED"] == 0
assert baseline_coverage("he_IL")["GOTHIC_18_EXTENDED"] > 0
assert baseline_coverage("en_IL") == baseline_coverage("en_US")
assert baseline_coverage("zz_ZZ") is None
owner = component()
assert (
    owner.repo == "local:"
    and owner.vcs == "local"
    and owner.project.access_control == 100
)
credentials = json.loads(Path("/app/data/peblate-demo-accounts.json").read_text())
with tempfile.TemporaryDirectory(prefix="peblate-permissions-") as temp:
    root = Path(temp) / "repo"
    with owner.repository.lock:
        assert not owner.repository.execute(["remote"], remote_op="none").strip()
        subprocess.run(
            ["git", "clone", "--no-local", owner.full_path, str(root)],
            check=True,
            capture_output=True,
        )
    for args in (
        ["remote", "remove", "origin"],
        ["config", "user.name", "Peblate test"],
        ["config", "user.email", "test@localhost"],
    ):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
    repository = LocalRepository(str(root), local=True)

    def git(args):
        return repository.execute(args, remote_op="none")

    with repository.lock:
        # Keep the empty-source case independent of fonts added to the live demo.
        map_path = (
            root / Path(translation_for_code("he_IL").filename).parent / "lang_map.json"
        )
        mapping = json.loads(map_path.read_text())
        for entry in mapping["fonts"]:
            if entry["name"] == "GOTHIC_36_BOLD_EXTENDED":
                entry["file"] = ""
                entry.pop("license", None)
        map_path.write_text(json.dumps(mapping))
        git(["add", str(map_path.relative_to(root))])
        git(["commit", "--allow-empty", "-m", "Set isolated empty-font fixture"])
    store = AssetStore(root, git, repository.lock)

    def test_store(code):
        translation = owner.translation_set.get(
            Q(language_code=code) | Q(language__code=code)
        )
        return store, Path(translation.filename)

    with (
        patch("peblate.views.language_store", test_store),
        patch("peblate.job_views.run_language_job.apply_async"),
        patch("peblate.views.CACHE_ROOT", Path(temp) / "cache"),
    ):
        for role, expected in [
            ("translator", (True, True, True)),
            ("reviewer", (True, True, True)),
            ("viewer", (True, False, False)),
            ("french-only", (False, False, False)),
            ("outsider", (False, False, False)),
        ]:
            username = "peblate-" + role
            client = Client()
            assert client.login(username=username, password=credentials[username]), role
            user = get_user_model().objects.get(username=username)
            assert not user.is_superuser
            translation = translation_for_code("he_IL")
            assert tuple(capabilities(user, translation).values()) == expected, (
                role,
                capabilities(user, translation),
            )
            assert bool(user.has_perm("unit.review", translation.unit_set.first())) == (
                role == "reviewer"
            ), role
            page = client.get(
                "/translate/pebbleos/watch/he_IL/?checksum=b80f6c8199ee8d30"
            )
            assert (b'id="pebble-editor-panel-template"' in page.content) == expected[
                0
            ], role
            if role == "viewer":
                assert page.content.count(b"<fieldset disabled>") >= 2
            with store.lock:
                before = git(["rev-parse", "HEAD"])
            response = client.get("/pebble/he_IL/font/GOTHIC_18_EXTENDED/")
            assert response.status_code == (200 if expected[0] else 403), (
                role,
                response.status_code,
            )
            response = client.post(
                "/pebble/he_IL/font/GOTHIC_18_EXTENDED/pbf/", {"text": "שלום"}
            )
            assert response.status_code == (200 if expected[0] else 403), (
                role,
                response.status_code,
            )
            response = client.post(
                "/pebble/he_IL/font/",
                {
                    "slot": "GOTHIC_18_EXTENDED",
                    "format": "json",
                    "font": SimpleUploadedFile(
                        "Heebo-Regular.ttf",
                        Path("/prototype/hebrew-fonts/Heebo-Regular.ttf").read_bytes(),
                    ),
                    "license": SimpleUploadedFile(
                        "LICENSE.Heebo.txt",
                        Path("/prototype/hebrew-fonts/LICENSE.Heebo.txt").read_bytes(),
                    ),
                },
            )
            assert response.status_code == (200 if expected[1] else 403), (
                role,
                response.status_code,
                response.content[:150],
            )
            response = client.post(
                "/pebble/he_IL/font/",
                {
                    "slot": "GOTHIC_28_EXTENDED",
                    "reuse_slot": "GOTHIC_18_EXTENDED",
                    "format": "json",
                },
            )
            assert response.status_code == (200 if expected[1] else 403), (
                response.content[:150]
            )
            if expected[1]:
                with store.lock:
                    mapping = store.mapping(Path(translation.filename), "he_IL")
                    entries = {entry["name"]: entry for entry in mapping["fonts"]}
                    for key in ("file", "license"):
                        assert (
                            entries["GOTHIC_28_EXTENDED"][key]
                            == entries["GOTHIC_18_EXTENDED"][key]
                        )
                    reused_head = git(["rev-parse", "HEAD"])
                response = client.post(
                    "/pebble/he_IL/font/",
                    {
                        "slot": "GOTHIC_28_EXTENDED",
                        "reuse_slot": "GOTHIC_18_EXTENDED",
                        "format": "json",
                    },
                )
                assert response.status_code == 200
                with store.lock:
                    assert git(["rev-parse", "HEAD"]) == reused_head
                for source in ("../other/font.ttf", "GOTHIC_36_BOLD_EXTENDED"):
                    assert (
                        client.post(
                            "/pebble/he_IL/font/",
                            {"slot": "GOTHIC_28_EXTENDED", "reuse_slot": source},
                        ).status_code
                        == 400
                    )
            for action in ("validate", "build"):
                response = client.post(
                    "/pebble/he_IL/validate/", {"action": action, "format": "json"}
                )
                assert response.status_code == (202 if expected[2] else 403), (
                    role,
                    action,
                    response.status_code,
                    response.content[:150],
                )
                if expected[2]:
                    LanguageJob.objects.filter(pk=response.json()["id"]).delete()
            if not expected[1]:
                with store.lock:
                    assert git(["rev-parse", "HEAD"]) == before
            if role == "french-only":
                assert capabilities(user, translation_for_code("fr"))["upload"]
                response = client.post("/pebble/fr/validate/", {"format": "json"})
                assert response.status_code == 202
                LanguageJob.objects.filter(pk=response.json()["id"]).delete()
            print(role, "preview/upload/build:", expected)
        anonymous = Client()
        for path in (
            "/pebble/he_IL/font/",
            "/pebble/he_IL/font/GOTHIC_18_EXTENDED/pbf/",
            "/pebble/he_IL/validate/",
        ):
            assert anonymous.post(path).status_code == 302
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(get_user_model().objects.get(username="peblate-translator"))
        assert csrf.post("/pebble/he_IL/font/", {}).status_code == 403
print(
    "Component/language scopes, review role, denied mutations, login and CSRF checks passed"
)
