"""Exercise pre-creation font drafts against a disposable local component.

Copy en_IL, en_SA and en_TW into /tmp/peblate-font-packs before running.
"""

import json
import shutil
import subprocess
import uuid
from pathlib import Path
from unittest.mock import patch

import polib
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, override_settings
from weblate.lang.models import Language
from weblate.trans.models import Component, Project
from weblate.trans.tasks import _remove_project

from peblate.language_policy import TRANSLATION_LANGUAGE_FILTER
from peblate.models import FontOwnership

fixtures = Path("/tmp/peblate-font-packs")
assert (fixtures / "en_IL/lang_map.json").is_file()
with (
    patch("weblate.trans.tasks.component_after_save.delay_on_commit"),
    patch("weblate.trans.models.Component.create_translations", return_value=True),
):
    slug = "setup-test-" + uuid.uuid4().hex[:8]
    project = Project.objects.create(slug=slug, name=slug, web="http://localhost/")
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
            new_lang="add",
            inherit_new_lang=False,
            file_format="po",
            source_language=Language.objects.get(code="en"),
            language_code_style="posix_long",
            inherit_language_code_style=False,
            license="Apache-2.0",
            language_regex=TRANSLATION_LANGUAGE_FILTER,
        )
        root = Path(owner.full_path)
        root.mkdir(parents=True, exist_ok=True)

        def git(*args):
            return subprocess.check_output(
                ["git", "-C", str(root), *args], text=True
            ).strip()

        git("init", "-b", "main")
        git("config", "user.name", "Setup test")
        git("config", "user.email", "test@localhost")
        source = polib.POFile()
        source.metadata = {
            "Project-Id-Version": "1",
            "MIME-Version": "1.0",
            "Content-Type": "text/plain; charset=UTF-8",
            "Content-Transfer-Encoding": "8bit",
        }
        source.append(polib.POEntry(msgid="Music"))
        source.save(str(root / "source.pot"))
        for pack in ("en_IL", "en_SA", "en_TW"):
            shutil.copytree(fixtures / pack, root / pack)
        git("add", ".")
        git("commit", "-m", "Seed")
        owner.sync_git_repo(skip_push=True)
        owner.create_translations_immediate(force=True)
        admin = get_user_model().objects.get(username="admin")
        client = Client()
        client.force_login(admin)
        url = f"/new-lang/{slug}/watch/"
        with override_settings(PEBLATE_COMPONENT=f"{slug}/watch"):
            before = git("rev-parse", "HEAD")
            response = client.get("/pebble/setup/coverage/", {"language": "he_IL"})
            assert response.status_code == 200, response.content[:500]
            assert response.json()["packs"][0] == {
                "code": "en_IL",
                "complete": True,
                "missing": 0,
                "licensed": True,
            }
            assert (
                client.get("/pebble/setup/coverage/", {"language": "ko"}).json()[
                    "packs"
                ]
                == []
            )
            for language, pack in (("ar", "en_SA"), ("zh_Hant", "en_TW")):
                response = client.get("/pebble/setup/coverage/", {"language": language})
                assert response.status_code == 200, response.content[:500]
                assert response.json()["packs"][0]["code"] == pack
            assert client.post(url, {"lang": "he_IL"}).status_code == 400
            assert not owner.translation_set.filter(language__code="he_IL").exists()
            response = client.post(
                "/pebble/setup/prepare/", {"language": "he_IL", "pack": "en_IL"}
            )
            assert response.status_code == 200, response.content[:1500]
            draft = response.json()
            assert draft["ready"] and draft["complete"], draft
            assert git("rev-parse", "HEAD") == before
            assert not (root / "he_IL").exists()
            print(
                "PASS: pack suggestions, required font gate, compilation before creation, no repository mutation"
            )
            token = draft["token"]
            from django.core import signing

            with patch(
                "peblate.setup_views.signing.loads",
                side_effect=signing.SignatureExpired("expired"),
            ):
                assert (
                    client.post(
                        url,
                        {
                            "lang": "he_IL",
                            "font_review": token,
                            "rendering_reviewed": "yes",
                        },
                    ).status_code
                    == 400
                )
            # A valid signature for a different owner cannot access this draft.
            payload = signing.loads(token, salt="peblate-setup")
            payload["user"] = -1
            foreign = signing.dumps(payload, salt="peblate-setup")
            assert (
                client.post(
                    "/pebble/setup/preview/GOTHIC_18_EXTENDED/",
                    {"language": "he_IL", "token": foreign},
                ).status_code
                == 400
            )
            with patch(
                "peblate.asset_store.AssetStore._commit",
                side_effect=ValueError("simulated commit failure"),
            ):
                response = client.post(
                    url,
                    {
                        "lang": "he_IL",
                        "font_review": token,
                        "rendering_reviewed": "yes",
                    },
                )
                assert response.status_code == 400
            assert not owner.translation_set.filter(language__code="he_IL").exists()
            assert not (root / "he_IL/tintin.po").exists()
            assert git("rev-parse", "HEAD") == before

            assert (
                client.post(url, {"lang": "he_IL", "font_review": token}).status_code
                == 400
            )
            assert (
                client.post(
                    url,
                    {"lang": "ar", "font_review": token, "rendering_reviewed": "yes"},
                ).status_code
                == 400
            )
            assert (
                client.post(
                    url,
                    {
                        "lang": "he_IL",
                        "font_review": token + "tampered",
                        "rendering_reviewed": "yes",
                    },
                ).status_code
                == 400
            )
            assert (
                client.post(
                    "/pebble/setup/preview/GOTHIC_18_EXTENDED/",
                    {"language": "he_IL", "token": token},
                ).status_code
                == 200
            )
            response = client.post(
                url,
                {"lang": "he_IL", "font_review": token, "rendering_reviewed": "yes"},
            )
            assert response.status_code == 302, response.content[:1500]
            from django.contrib.messages import get_messages

            assert owner.translation_set.filter(language__code="he_IL").exists(), (
                response.url,
                [str(m) for m in get_messages(response.wsgi_request)],
            )
            mapping = json.loads((root / "he_IL/lang_map.json").read_text())
            assert len(mapping["fonts"]) == 10
            created_translation = owner.translation_set.get(language__code="he_IL")
            assert (
                FontOwnership.objects.filter(
                    translation=created_translation, owner=admin
                ).count()
                == 10
            )
            assert all(
                (root / "he_IL" / entry["license"]).is_file()
                for entry in mapping["fonts"]
            )
            assert not polib.pofile(str(root / "he_IL/tintin.po")).find("Music").msgstr
            commits = git("log", "--format=%s", f"{before}..HEAD").splitlines()
            assert len(commits) == 1, commits
            assert "he_IL/tintin.po" in git("show", "--format=", "--name-only", "HEAD")
            print(
                "PASS: review, language and token checks; catalog, fonts and licenses committed together"
            )
            # Upload before creating Yiddish, which uses the same Hebrew font.
            response = client.post(
                "/pebble/setup/prepare/",
                {
                    "language": "yi",
                    "font": SimpleUploadedFile(
                        "Heebo.ttf", (fixtures / "en_IL/Heebo-Regular.ttf").read_bytes()
                    ),
                },
            )
            assert response.status_code == 400 and b"license" in response.content
            response = client.post(
                "/pebble/setup/prepare/",
                {
                    "language": "yi",
                    "font": SimpleUploadedFile(
                        "Heebo.ttf", (fixtures / "en_IL/Heebo-Regular.ttf").read_bytes()
                    ),
                    "license": SimpleUploadedFile(
                        "LICENSE.txt",
                        (fixtures / "en_IL/LICENSE.Heebo.txt").read_bytes(),
                    ),
                },
            )
            assert response.status_code == 200, response.content[:1500]
            uploaded = response.json()
            response = client.post(
                url,
                {
                    "lang": "yi",
                    "font_review": uploaded["token"],
                    "rendering_reviewed": "yes",
                    "gaps_reviewed": "yes",
                },
            )
            assert response.status_code == 302, response.content[:1500]
            assert owner.translation_set.filter(language__code="yi").exists()
            response = client.post(url, {"lang": "fr"})
            assert response.status_code == 302, response.content[:500]
            assert owner.translation_set.filter(language__code="fr").exists()
            print(
                "PASS: upload plus mandatory license before creation; built-in-only creation"
            )
            response = client.post(
                "/pebble/setup/prepare/", {"language": "ar", "pack": "en_SA"}
            )
            assert response.status_code == 200, response.content[:1500]
            arabic = response.json()
            assert not arabic["complete"]
            assert (
                client.post(
                    url,
                    {
                        "lang": "ar",
                        "font_review": arabic["token"],
                        "rendering_reviewed": "yes",
                    },
                ).status_code
                == 400
            )
            response = client.post(
                url,
                {
                    "lang": "ar",
                    "font_review": arabic["token"],
                    "rendering_reviewed": "yes",
                    "gaps_reviewed": "yes",
                },
            )
            assert response.status_code == 302, response.content[:1500]
            mapping = json.loads((root / "ar_AA/lang_map.json").read_text())
            assert (
                next(
                    entry
                    for entry in mapping["fonts"]
                    if entry["name"] == "GOTHIC_18_EXTENDED"
                )["pixelHeight"]
                == 14
            )
            print(
                "PASS: partial coverage requires explicit acceptance; reused Arabic sizing preserved"
            )
            response = client.post(
                "/pebble/setup/prepare/", {"language": "zh_Hant", "pack": "en_TW"}
            )
            assert response.status_code == 200, response.content[:1500]
            chinese = response.json()
            response = client.post(
                url,
                {
                    "lang": "zh_Hant",
                    "font_review": chinese["token"],
                    "rendering_reviewed": "yes",
                    "gaps_reviewed": "yes",
                },
            )
            assert response.status_code == 302, response.content[:1500]
            translation = owner.translation_set.get(language__code="zh_Hant")
            mapping = json.loads(
                Path(translation.get_filename()).with_name("lang_map.json").read_text()
            )
            assert mapping["strings"]["lang"] == "zh_Hant"
            assert sum("alias" in entry for entry in mapping["fonts"]) == 6
            assert any(
                entry["name"] == "ROBOTO_CONDENSED_21_EXTENDED"
                for entry in mapping["fonts"]
            )
            response = client.post(
                f"/pebble/{translation.language_code}/font/GOTHIC_36_EXTENDED/pbf/",
                {"text": "中文"},
            )
            assert response.status_code == 200, response.content[:1500]
            print(
                "PASS: Chinese font aliases, extra date font, semantic locale, and editor preview preserved"
            )
            for code, locale in (("de", "de_DE"), ("nb", "nb_NO")):
                response = client.post(url, {"lang": code})
                assert response.status_code == 302, response.content[:1500]
                translation = owner.translation_set.get(language__code=code)
                mapping_path = Path(translation.get_filename()).with_name(
                    "lang_map.json"
                )
                mapping = json.loads(mapping_path.read_text())
                assert mapping["strings"] == {
                    "lang": locale,
                    "name": "STRINGS",
                    "file": "tintin.po",
                }, mapping
                assert mapping["fonts"] == []
                tracked = git("ls-files").splitlines()
                assert f"{locale}/lang_map.json" in tracked
                assert f"{locale}/tintin.po" in tracked
                assert not FontOwnership.objects.filter(
                    translation=translation
                ).exists()
            # Native API creation must initialize resources too, without a wizard draft.
            owner.add_new_language(
                Language.objects.get(code="fr"), None, show_messages=False
            )
            assert "fr_FR/lang_map.json" in git("ls-files").splitlines()
            assert not git("status", "--porcelain")
            print(
                "PASS: built-in-font languages commit resource maps through wizard and native creation"
            )
    finally:
        _remove_project(project.pk, None)
