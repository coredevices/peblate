"""Font ownership and native reviewer permissions; isolated Git and rolled-back DB."""

import json
import re
import subprocess
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.test import Client
from weblate.auth.models import Group, Role
from weblate.lang.models import Language
from weblate.vcs.git import LocalRepository

from peblate.asset_store import AssetStore
from peblate.font_permissions import font_access, record_ownership
from peblate.font_upload import validate_upload
from peblate.models import FontOwnership
from peblate.setup_views import creation_draft, install_creation_fonts
from peblate.weblate_adapter import component, translation_for_code

assert settings.SITE_DOMAIN == "localhost:8088"
owner = component()
assert owner.repo == "local:" and owner.vcs == "local"
translation = translation_for_code("he_IL")
catalog = Path(translation.filename)
User = get_user_model()
author = User.objects.get(username="peblate-translator")
reviewer = User.objects.get(username="peblate-reviewer")
admin = User.objects.get(username="admin")
font = Path("/prototype/hebrew-fonts/Heebo-Regular.ttf").read_bytes()
license_data = Path("/prototype/hebrew-fonts/LICENSE.Heebo.txt").read_bytes()
slot = "GOTHIC_18_EXTENDED"
empty_slot = "GOTHIC_24_EXTENDED"
alias_slot = "GOTHIC_28_EXTENDED"

with (
    transaction.atomic(),
    tempfile.TemporaryDirectory(prefix="font-ownership-") as temp,
    patch("celery.app.task.Task.apply_async"),
):
    root = Path(temp) / "repo"
    with owner.repository.lock:
        subprocess.run(
            ["git", "clone", "--no-local", owner.full_path, str(root)],
            check=True,
            capture_output=True,
        )
    for args in (
        ["remote", "remove", "origin"],
        ["config", "user.name", "Test"],
        ["config", "user.email", "test@localhost"],
    ):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
    repository = LocalRepository(str(root), local=True)

    def git(args):
        with repository.lock:
            return repository.execute(args, remote_op="none")

    store = AssetStore(root, git, repository.lock)
    mapping_path = store.path(catalog.with_name("lang_map.json"))

    def save_mapping(mapping):
        with store.lock:
            mapping_path.write_bytes(store.encode(mapping))
            git(["add", "--", str(catalog.with_name("lang_map.json"))])
            git(["commit", "--allow-empty", "-m", "Fixture mapping"])

    save_mapping(
        {
            "strings": {"name": "STRINGS", "file": catalog.name},
            "fonts": [],
            "images": [],
        }
    )
    FontOwnership.objects.filter(translation=translation).delete()
    stranger = User.objects.create_user(
        username="font-other-" + uuid.uuid4().hex[:8], email="other@example.test"
    )
    stranger.groups.set(author.groups.all())
    french_reviewer = User.objects.create_user(
        username="font-fr-" + uuid.uuid4().hex[:8], email="reviewer@example.test"
    )
    french_reviewer.groups.set(author.groups.all())
    group = Group.objects.create(
        name="Font reviewer " + uuid.uuid4().hex[:8],
        project_selection=0,
        language_selection=0,
    )
    group.projects.add(owner.project)
    group.components.add(owner)
    group.languages.add(Language.objects.get(code="fr"))
    group.roles.add(Role.objects.get(name="Review strings"))
    french_reviewer.groups.add(group)
    french_reviewer = User.objects.get(pk=french_reviewer.pk)
    assert reviewer.has_perm("unit.review", translation)
    assert not french_reviewer.has_perm("unit.review", translation)
    french_permission = french_reviewer.has_perm(
        "unit.review", translation_for_code("fr")
    )
    assert french_permission, getattr(
        french_permission, "reason", vars(french_permission)
    )

    def client_for(user):
        client = Client()
        client.force_login(user)
        return client

    clients = {
        user.pk: client_for(user)
        for user in (author, stranger, reviewer, admin, french_reviewer)
    }

    def upload(user, target=slot, *, reuse=None, filename="Heebo.ttf"):
        data = {"slot": target, "format": "json", "owner": str(user.pk)}
        if reuse:
            data["reuse_slot"] = reuse
        else:
            data.update(
                font=SimpleUploadedFile(filename, font),
                license=SimpleUploadedFile("LICENSE.txt", license_data),
            )
        return clients[user.pk].post("/pebble/he_IL/font/", data)

    def owner_id(target=slot):
        return FontOwnership.objects.get(translation=translation, slot=target).owner_id

    def page_slots(user):
        page = clients[user.pk].get(translation.get_translate_url())
        assert page.status_code == 200, page.status_code
        match = re.search(
            rb'<script id="pebble-slot-config" type="application/json">(.*?)</script>',
            page.content,
            re.DOTALL,
        )
        assert match, page.content[:200]
        return {item["name"]: item for item in json.loads(match[1])}

    with (
        patch("peblate.views.language_store", return_value=(store, catalog)),
        patch(
            "peblate.templatetags.pebble.language_store", return_value=(store, catalog)
        ),
    ):
        assert upload(author).status_code == 200
        assert owner_id() == author.pk
        head = git(["rev-parse", "HEAD"])
        assert upload(stranger).status_code == 403
        assert upload(stranger, reuse=slot).status_code == 403
        assert upload(french_reviewer).status_code == 403
        assert git(["rev-parse", "HEAD"]) == head
        assert page_slots(author)[slot]["can_upload"]
        assert not page_slots(stranger)[slot]["can_upload"]
        assert page_slots(stranger)[empty_slot]["can_upload"]
        assert upload(author, filename="Updated.ttf").status_code == 200
        assert owner_id() == author.pk
        assert upload(reviewer, filename="Updated.ttf").status_code == 200
        assert owner_id() == author.pk  # Identical upload cannot take ownership.
        assert upload(reviewer, filename="Reviewer.ttf").status_code == 200
        assert owner_id() == reviewer.pk
        assert upload(author).status_code == 403
        assert upload(admin).status_code == 200
        assert owner_id() == admin.pk
        print(
            "PASS: initial uploads, owners, unrelated users, language-scoped reviewers, admins, UI and no-op ownership"
        )

        # Reusing another style's bytes fills a new assignment, never overwrites
        # the source or permits replacement of a protected destination.
        assert upload(stranger, empty_slot, reuse=slot).status_code == 200
        assert owner_id(empty_slot) == stranger.pk and owner_id() == admin.pk
        assert upload(stranger, empty_slot, filename="Own.ttf").status_code == 200
        mapping = store.mapping(catalog, "he_IL")
        original = next(e for e in mapping["fonts"] if e["name"] == empty_slot)
        original["original_name"] = "Changed in Git.ttf"
        original["uploaded_by"] = stranger.pk  # Untrusted metadata grants nothing.
        save_mapping(mapping)
        assert upload(stranger, empty_slot).status_code == 403
        assert upload(reviewer, empty_slot).status_code == 200
        assert upload(stranger, "GOTHIC_14_EXTENDED").status_code == 200
        entry = next(
            e
            for e in store.mapping(catalog, "he_IL")["fonts"]
            if e["name"] == "GOTHIC_14_EXTENDED"
        )
        asset = store.resource(catalog, entry["file"])
        original_bytes = asset.read_bytes()
        asset.write_bytes(original_bytes + b"git-change")
        assert upload(stranger, "GOTHIC_14_EXTENDED").status_code == 403
        asset.write_bytes(original_bytes)

        # Imports have no owner, including aliases of owned assignments.
        mapping = store.mapping(catalog, "he_IL")
        mapping["fonts"].append({"name": alias_slot, "alias": "GOTHIC_14_EXTENDED"})
        save_mapping(mapping)
        assert upload(stranger, alias_slot).status_code == 403
        assert upload(stranger, "GOTHIC_14_EXTENDED").status_code == 403
        result = upload(reviewer, "GOTHIC_14_EXTENDED")
        assert result.status_code == 200
        assert {item["slot"] for item in result.json()["assignments"]} == {
            "GOTHIC_14_EXTENDED",
            alias_slot,
        }
        assert owner_id(alias_slot) == reviewer.pk
        print("PASS: reuse, imported fonts, aliases, Git metadata and byte changes")

        # Another contributor wins an initially empty slot while we validate.
        race_slot = "GOTHIC_36_EXTENDED"

        def race(*args, **kwargs):
            result = validate_upload(*args, **kwargs)
            with store.lock:
                store.upload(
                    catalog,
                    "he_IL",
                    race_slot,
                    font,
                    license_data,
                    "Other.ttf",
                    "LICENSE.txt",
                )
                record_ownership(
                    stranger,
                    translation,
                    store,
                    catalog,
                    store.mapping(catalog, "he_IL"),
                    [race_slot],
                )
            return result

        with patch("peblate.font_upload.validate_upload", side_effect=race):
            assert upload(author, race_slot).status_code == 403
        assert owner_id(race_slot) == stranger.pk
        head = git(["rev-parse", "HEAD"])
        with patch.object(store, "_commit", side_effect=ValueError("commit failure")):
            assert upload(reviewer, race_slot).status_code == 400
        assert owner_id(race_slot) == stranger.pk
        assert git(["rev-parse", "HEAD"]) == head
        stranger.delete()
        assert owner_id(race_slot) is None
        assert upload(author, race_slot).status_code == 403
        print("PASS: concurrent initial upload, failed commit, deleted uploader")

        # Exercise the creation signal as a contributor using an untracked
        # catalog and a private prepared font draft in the disposable repository.
        prepared = Path(temp) / "prepared"
        prepared.mkdir()
        (prepared / "font.ttf").write_bytes(font)
        (prepared / "license.txt").write_bytes(license_data)
        (prepared / "fonts.json").write_text(
            json.dumps([{"name": slot, "file": "font.ttf", "license": "license.txt"}])
        )
        new_catalog = root / "created/tintin.po"
        new_catalog.parent.mkdir()
        new_catalog.write_text('msgid "Music"\nmsgstr ""\n')
        token = creation_draft.set(
            {
                "component": owner.pk,
                "language": translation.language.code,
                "folder": prepared,
                "user": author,
            }
        )
        try:
            with (
                patch("peblate.setup_views.component_store", return_value=store),
                patch.object(
                    type(translation), "get_filename", return_value=str(new_catalog)
                ),
            ):
                install_creation_fonts(None, translation)
        finally:
            creation_draft.reset(token)
        assert owner_id() == author.pk
        with store.lock:
            _, allowed = font_access(
                author,
                translation,
                store,
                Path("created/tintin.po"),
                store.mapping(Path("created/tintin.po"), "he_IL"),
            )
        assert allowed[slot]
        print("PASS: wizard-created fonts belong to the contributor")
    transaction.set_rollback(True)
