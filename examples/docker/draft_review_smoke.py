# SPDX-FileCopyrightText: 2026 Core Devices LLC
# SPDX-License-Identifier: Apache-2.0

"""Build unreviewed drafts without changing Git, approvals, or pending edits."""

import gettext
import io
import struct
import subprocess
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch

import polib
from celery.result import AsyncResult
from django.contrib.auth import get_user_model
from django.test import Client, override_settings
from weblate.auth.models import Group, Role
from weblate.lang.models import Language
from weblate.trans.models import Component, Project
from weblate.trans.models.project import CommitPolicyChoices
from weblate.trans.tasks import _remove_project

from peblate import tasks
from peblate.models import LanguageJob
from peblate.permissions import capabilities


def strings(pack):
    resource_id, offset, length, _ = struct.unpack_from("<IIII", pack, 12)
    assert resource_id == 1
    start = 12 + 256 * 16 + offset
    return gettext.GNUTranslations(io.BytesIO(pack[start : start + length]))


slug = "draft-test-" + uuid.uuid4().hex[:8]
with (
    tempfile.TemporaryDirectory(prefix=slug) as cache,
    # Run all work synchronously so unrelated workers cannot race fixture cleanup.
    patch(
        "celery.app.task.Task.apply_async", return_value=AsyncResult(str(uuid.uuid4()))
    ),
    patch("weblate.trans.models.Component.queue_background_task"),
    patch("weblate.trans.models.Component.create_translations", return_value=True),
):
    project = Project.objects.create(
        slug=slug,
        name=slug,
        web="http://localhost/",
        access_control=100,
        translation_review=True,
        commit_policy=CommitPolicyChoices.APPROVED_ONLY,
    )
    user = get_user_model().objects.create(
        username=slug, email=f"{slug}@localhost.test"
    )
    group = Group.objects.create(name=slug, project_selection=0, language_selection=1)
    group.projects.add(project)
    group.roles.add(Role.objects.get(name="Translate"))
    user.groups.set([group])
    try:
        owner = Component.objects.create(
            project=project,
            slug="watch",
            name="Watch",
            repo="local:",
            vcs="local",
            branch="main",
            filemask="*/tintin.po",
            new_base="source.pot",
            file_format="po",
            source_language=Language.objects.get(code="en"),
            license="Apache-2.0",
        )
        group.components.add(owner)
        repo = Path(owner.full_path)
        repo.mkdir(parents=True, exist_ok=True)

        def git(*args):
            return subprocess.check_output(
                ["git", "-C", str(repo), *args], text=True
            ).strip()

        git("init", "-b", "main")
        git("config", "user.name", "Draft test")
        git("config", "user.email", "test@localhost")
        source = polib.POFile()
        source.metadata = {
            "Project-Id-Version": "1",
            "MIME-Version": "1.0",
            "Content-Type": "text/plain; charset=UTF-8",
            "Content-Transfer-Encoding": "8bit",
            "Name": "Français",
        }
        for text in ("Music", "Approved", "New", "Fuzzy", "Empty"):
            source.append(polib.POEntry(msgid=text))
        source.append(polib.POEntry(msgid="Open", msgctxt="verb"))
        source.append(polib.POEntry(msgid="Open", msgctxt="adjective"))
        source.append(
            polib.POEntry(
                msgid="%d item",
                msgid_plural="%d items",
                msgstr_plural={0: "", 1: ""},
                flags=["c-format"],
            )
        )
        source.save(str(repo / "source.pot"))
        source.metadata.update(
            {"Language": "fr", "Plural-Forms": "nplurals=2; plural=(n > 1);"}
        )
        source.find("Music").msgstr = "Musique publiée"
        source.find("Approved").msgstr = "Ancien"
        (repo / "fr").mkdir()
        catalog = repo / "fr/tintin.po"
        source.save(str(catalog))
        # Deliberately omit lang_map.json: draft checks must not initialize it in Git.
        git("add", ".")
        git("commit", "-m", "Seed draft test")
        assert git("remote") == ""
        owner.sync_git_repo(skip_push=True)
        owner.create_translations_immediate(force=True)
        translation = owner.translation_set.get(language_code="fr")
        assert translation.enable_review
        assert capabilities(user, translation)["validate"], capabilities(
            user, translation
        )
        assert not user.has_perm("unit.review", translation)
        admin = get_user_model().objects.get(username="admin")

        def edit(source, target, state=20, **lookup):
            unit = translation.unit_set.get(source=source, **lookup)
            unit.translate(
                admin if state == 30 else user, target, state, propagate=False
            )
            return unit

        music = edit("Music", "Musique brouillon")
        edit("Approved", "Approuvé", 30)
        edit("New", "Nouveau")
        edit("Fuzzy", "À corriger", 10)
        edit("Open", "Ouvrir", context="verb")
        edit("Open", "Ouvert", context="adjective")
        plural = translation.unit_set.get(source__startswith="%d item")
        plural.translate(user, ["%d objet", "%d objets"], 20, propagate=False)
        client = Client()
        client.force_login(user)

        def unchanged():
            return (
                git("rev-parse", "HEAD"),
                git("status", "--porcelain"),
                catalog.read_bytes(),
                list(
                    translation.unit_set.order_by("pk").values_list(
                        "pk", "target", "state"
                    )
                ),
                list(music.pending_changes.order_by("pk").values_list("pk", flat=True)),
            )

        with override_settings(
            PEBLATE_COMPONENT=f"{slug}/watch", PEBLATE_CACHE_ROOT=cache
        ):
            before = unchanged()
            compile_snapshot = tasks.compile_snapshot

            def inspect_snapshot(job, root):
                draft = polib.pofile(str(root / "fr/tintin.po"))
                assert draft.find("Music").msgstr == "Musique brouillon"
                assert draft.metadata["Name"] == "Français"
                assert draft.metadata["Project-Id-Version"] == "1"
                assert draft.find("Fuzzy").fuzzy
                assert draft.find("Empty").msgstr == ""
                assert draft.find("%d item").msgstr_plural == {
                    0: "%d objet",
                    1: "%d objets",
                }
                assert draft.find("Open", msgctxt="verb").msgstr == "Ouvrir"
                assert unchanged() == before
                return compile_snapshot(job, root)

            def build():
                with patch("peblate.job_views.run_language_job.apply_async"):
                    response = client.post(
                        "/pebble/fr/validate/", {"action": "build", "format": "json"}
                    )
                assert response.status_code == 202, (
                    response.status_code,
                    response.content[-3000:],
                )
                job = response.json()
                tasks.run_language_job.run(job["id"])
                result = client.get(job["status_url"]).json()
                assert result["status"] == "succeeded" and result["download_url"], (
                    result
                )
                return result, b"".join(
                    client.get(result["download_url"]).streaming_content
                )

            with patch("peblate.tasks.compile_snapshot", inspect_snapshot):
                result, pack = build()
            assert unchanged() == before
            assert not (repo / "fr/lang_map.json").exists()
            compiled = strings(pack)
            assert compiled.gettext("Music") == "Musique brouillon"
            assert compiled.gettext("Approved") == "Approuvé"
            assert compiled.gettext("New") == "Nouveau"
            assert compiled.gettext("Fuzzy") == "Fuzzy"
            assert compiled.gettext("Empty") == "Empty"
            assert compiled.pgettext("verb", "Open") == "Ouvrir"
            assert compiled.pgettext("adjective", "Open") == "Ouvert"
            assert compiled.ngettext("%d item", "%d items", 2) == "%d objets"
            print(
                "PASS: unreviewed draft pack, contexts, plurals, fuzzy exclusion; Git and approvals untouched"
            )

            edit("Music", "Musique suivante")
            _, newer = build()
            assert strings(newer).gettext("Music") == "Musique suivante"
            assert (
                b"".join(client.get(result["download_url"]).streaming_content) == pack
            )
            # Exercise the actual approved-only commit path after both drafts.
            translation.commit_pending("draft-test", admin, skip_push=True)
            published = polib.pofile(str(catalog))
            assert published.find("Music").msgstr == "Musique publiée"
            assert published.find("Approved").msgstr == "Approuvé"
            assert published.find("New").msgstr == ""
            assert music.pending_changes.exists()
            print(
                "PASS: later edits require another draft; approved-only Git retains the published string"
            )

            project.commit_policy = CommitPolicyChoices.ALL
            project.save(update_fields=["commit_policy"])
            before = unchanged()
            _, ordinary = build()
            assert strings(ordinary).gettext("Music") == "Musique suivante"
            assert unchanged() == before
            print(
                "PASS: drafts do not flush pending edits under the ordinary commit policy either"
            )
    finally:
        LanguageJob.objects.filter(translation__component__project=project).delete()
        _remove_project(project.pk, None)
        group.delete()
        user.delete()
