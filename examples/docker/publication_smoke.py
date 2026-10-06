"""Local Weblate publication workflow; database decisions are rolled back."""

import shutil
from pathlib import Path
from unittest.mock import patch

import polib
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import Client
from pebble_language_tools.lang_commands import new_map
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient
from weblate.auth.models import Group, Role, TeamMembership
from weblate.lang.models import Language
from weblate.utils.state import STATE_APPROVED, STATE_TRANSLATED

from peblate.models import FontApproval, LanguageJob, PublicationSettings
from peblate.publication import evidence, reviewers_for
from peblate.tasks import job_folder, run_language_job
from peblate.weblate_adapter import component, component_store, translation_for_code

assert settings.SITE_DOMAIN == "localhost:8088", "Local prototype only"
User = get_user_model()
owner = component()
translation = translation_for_code("fr")
admin = User.objects.get(username="admin")
reader = User.objects.get(username="peblate-viewer")
translator = User.objects.get(username="peblate-translator")
glossary_folder = None
job_ids = []
font_folder = None
base = "/pebble/publication/"
locale = Path(translation.get_filename()).parent.name
page = base + locale + "/"
api_path = "/api/pebble/release/" + locale + "/"
try:
    with (
        transaction.atomic(),
        patch("celery.app.task.Task.apply_async"),
        patch("weblate.trans.models.Component.queue_background_task"),
    ):
        client = Client()
        client.force_login(admin)
        assert client.get(base).status_code == 200
        assert client.get(page).status_code == 200
        before = translation.unit_set.filter(state=STATE_APPROVED).count()
        assert (
            client.post(
                base, {"enabled": "on", "minimum_approved_percent": 80}
            ).status_code
            == 302
        )
        assert PublicationSettings.objects.get(component=owner).enabled
        owner.refresh_from_db()
        glossary_folder = Path(
            owner.project.component_set.get(slug="pebble-glossary").full_path
        )
        assert translation.unit_set.filter(state=STATE_APPROVED).count() == before
        assert (
            client.post(
                base, {"enabled": "on", "minimum_approved_percent": 79}
            ).status_code
            == 200
        )
        assert (
            PublicationSettings.objects.get(component=owner).minimum_approved_percent
            == 80
        )
        assert client.get(page + "approve/").status_code == 405
        protected = Client(enforce_csrf_checks=True)
        protected.force_login(admin)
        assert protected.post(page + "approve/", {}).status_code == 403
        client.force_login(translator)
        assert client.get(page).status_code == 200
        for route in (base, page + "approve/", page + "revoke/", page + "check/"):
            assert client.post(route, {}).status_code == 403, route
        # Only explicit native language review grants count, not admin powers.
        assert admin.username not in reviewers_for(translation)
        reviewer = User.objects.create_user(
            username="publication-fr-reviewer", email="reviewer@example.test"
        )
        reviewer.groups.set(translator.groups.all())
        team = Group.objects.create(
            name="Publication French reviewers",
            project_selection=0,
            language_selection=0,
        )
        team.projects.add(owner.project)
        team.components.add(owner)
        team.languages.add(Language.objects.get(code="fr"))
        team.roles.add(Role.objects.get(name="Review strings"))
        reviewer.groups.add(team)
        assert reviewers_for(translation) == [reviewer.username]
        assert reviewer.username not in reviewers_for(translation_for_code("it"))
        # Per-member language limits are also native language reviewer grants.
        team.language_selection = 1
        team.save(update_fields=["language_selection"])
        TeamMembership.objects.get(user=reviewer, group=team).limit_languages.add(
            translation.language
        )
        reviewer = User.objects.get(pk=reviewer.pk)
        assert reviewer.username in reviewers_for(translation)
        # Real native token authentication, never a special release API secret.
        api = APIClient()
        token, _ = Token.objects.get_or_create(user=reader)
        api.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        approved = translation.unit_set.first()
        approved.target = "APPROVED TEST"
        approved.state = STATE_APPROVED
        approved.save(update_fields=["target", "state"])
        other = translation.unit_set.exclude(pk=approved.pk).exclude(source="").first()
        other.target = "UNREVIEWED TEST"
        other.state = STATE_TRANSLATED
        other.save(update_fields=["target", "state"])
        response = api.get(api_path)
        assert response.status_code == 200, response.content[:500]
        data = response.json()
        assert data["reviewers"] == [reviewer.username]
        assert (
            data["publicationEnabled"]
            and data["reviewEnabled"]
            and data["approvedOnlyCommits"]
        )
        exported = polib.pofile(data["catalog"])
        assert any(e.msgstr == "APPROVED TEST" for e in exported)
        assert not any(e.msgstr == "UNREVIEWED TEST" for e in exported)
        assert api.post(api_path, {}).status_code == 405
        # Build a real private draft without changing Git or review states.
        safe_catalog = polib.POFile()
        safe_catalog.metadata = polib.pofile(translation.get_filename()).metadata
        safe_catalog.metadata["Plural-Forms"] = translation.plural.plural_form
        safe_catalog.append(polib.POEntry(msgid="Hello", msgstr="Bonjour"))
        client.force_login(admin)
        assert client.post(page + "check/", {}).status_code == 302
        job = LanguageJob.objects.filter(
            owner=admin, translation=translation, operation="build", status="queued"
        ).latest("created_at")
        job_ids.append(job.pk)
        with patch(
            "peblate.tasks.draft_catalog", return_value=str(safe_catalog).encode()
        ):
            run_language_job.run(str(job.pk))
        job.refresh_from_db()
        assert job.status == "succeeded" and job.report["ok"], (job.error, job.report)
        assert (
            job.font_input_hash
            and (job_folder(job.pk) / "dist" / f"{locale}.pbl").is_file()
        )
        assert client.get(page).status_code == 200
        post = {
            "job": str(job.pk),
            "redistribution": "on",
            "rendering": "on",
            "accept_gaps": "on",
            "accept_unknown": "on",
            "note": "Reviewed license and watch rendering",
        }
        assert client.post(page + "approve/", {"job": str(job.pk)}).status_code == 400
        with patch("peblate.publication_views.font_inputs", return_value="changed"):
            assert client.post(page + "approve/", post).status_code == 409
        assert client.post(page + "approve/", post).status_code == 302
        assert evidence(owner, locale)["fontApproval"]["approvedBy"] == admin.username
        with patch("peblate.publication.font_inputs", return_value="changed"):
            assert evidence(owner, locale)["fontApproval"] is None
        reviewer.is_active = False
        reviewer.save(update_fields=["is_active"])
        assert reviewer.username not in evidence(owner, locale)["reviewers"]
        # Revoked maintainer authority invalidates approval at export time.
        with patch("peblate.publication.is_maintainer", return_value=False):
            assert evidence(owner, locale)["fontApproval"] is None
        assert client.post(page + "revoke/", {}).status_code == 302
        assert not FontApproval.objects.filter(component=owner, locale=locale).exists()
        # Test a real font-only pack without introducing a translation target.
        font_locale = "en_TEST"
        store = component_store(owner)
        font_folder = store.path(font_locale)
        assert not font_folder.exists()
        font_folder.mkdir()
        original = polib.POFile()
        original.metadata = dict(safe_catalog.metadata)
        original.append(polib.POEntry(msgid="Hello", msgstr="MUST NOT SHIP"))
        original.save(str(font_folder / "tintin.po"))
        (font_folder / "lang_map.json").write_bytes(store.encode(new_map(font_locale)))
        font_page = base + font_locale + "/"
        assert client.get(font_page).status_code == 200
        assert (
            client.post(
                font_page + "check/", {"coverage_language": "invalid-code"}
            ).status_code
            == 400
        )
        assert (
            client.post(font_page + "check/", {"coverage_language": "en"}).status_code
            == 302
        )
        font_job = LanguageJob.objects.get(
            owner=admin,
            translation=None,
            component=owner,
            locale=font_locale,
            status="queued",
        )
        job_ids.append(font_job.pk)
        run_language_job.run(str(font_job.pk))
        font_job.refresh_from_db()
        assert font_job.status == "succeeded" and font_job.report["ok"], (
            font_job.error,
            font_job.report,
        )
        assert client.get(font_page).status_code == 200
        post["job"] = str(font_job.pk)
        assert client.post(font_page + "approve/", post).status_code == 302
        font_data = api.get("/api/pebble/release/" + font_locale + "/").json()
        assert (
            font_data["kind"] == "font-only" and font_data["coverageLanguage"] == "en"
        )
        assert font_data["fontApproval"] and not font_data["reviewers"]
        import struct

        from pebble_language_tools.pack_format import TABLE_SIZE

        pack = (job_folder(font_job.pk) / "dist" / (font_locale + ".pbl")).read_bytes()
        _, offset, size, _ = struct.unpack_from("<IIII", pack, 12)
        mo = polib.mofile(
            pack[12 + TABLE_SIZE * 16 + offset : 12 + TABLE_SIZE * 16 + offset + size]
        )
        assert not any(entry.msgstr == "MUST NOT SHIP" for entry in mo)
        transaction.set_rollback(True)
finally:
    for job_id in job_ids:
        shutil.rmtree(job_folder(job_id), ignore_errors=True)
    if font_folder:
        shutil.rmtree(font_folder, ignore_errors=True)
    if glossary_folder and glossary_folder.resolve().is_relative_to(
        Path("/app/data/vcs").resolve()
    ):
        shutil.rmtree(glossary_folder, ignore_errors=True)
print(
    "PASS: Weblate settings, native scoped reviewers, approved-only API, draft build, stale-input protection, maintainer-only approvals, revocation and CSRF"
)
