# SPDX-FileCopyrightText: 2026 Core Devices LLC
# SPDX-License-Identifier: Apache-2.0

"""Verify English font packs stay in Git but cannot be translated in Weblate."""

import subprocess
import uuid
from pathlib import Path
from unittest.mock import patch

import polib
from django import forms
from django.core.management import call_command
from django.test.utils import override_settings
from peblate.templatetags.pebble import pebble_translation_choices
from weblate.lang.models import Language
from weblate.trans.models import Component, Project
from weblate.trans.tasks import _remove_project

with patch("weblate.trans.tasks.component_after_save.delay_on_commit"):
    slug = "font-policy-test-" + uuid.uuid4().hex[:8]
    project = Project.objects.create(
        slug=slug, name="Disposable source import test " + slug, web="http://localhost/"
    )
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
        )
        root = Path(owner.full_path)
        root.mkdir(parents=True, exist_ok=True)

        def git(*args):
            return subprocess.check_output(
                ["git", "-C", str(root), *args], text=True
            ).strip()

        git("init", "-b", "main")
        git("config", "user.name", "Source integration test")
        git("config", "user.email", "test@localhost")
        metadata = {
            "Project-Id-Version": "PebbleOS",
            "MIME-Version": "1.0",
            "Content-Type": "text/plain; charset=UTF-8",
            "Content-Transfer-Encoding": "8bit",
        }
        source = polib.POFile()
        source.metadata = metadata.copy()
        source.append(polib.POEntry(msgid="Keep"))
        source.append(polib.POEntry(msgid="Remove"))
        source.append(polib.POEntry(msgid="Open", msgctxt="verb"))
        source.save(str(root / "source.pot"))
        for locale, language in [("fr_FR", "fr"), ("en_IL", "en")]:
            folder = root / locale
            folder.mkdir()
            catalog = polib.pofile(str(root / "source.pot"))
            catalog.metadata.update(
                {"Language": locale, "Plural-Forms": "nplurals=2; plural=(n != 1);"}
            )
            catalog.find("Keep").msgstr = "Garder" if language == "fr" else "Behalten"
            catalog.find("Remove").msgstr = (
                "Retirer" if language == "fr" else "Entfernen"
            )
            catalog.save(str(folder / "tintin.po"))
            (folder / "lang_map.json").write_text("{}")
            (folder / "font.ttf").write_bytes(b"font-fixture")
        git("add", ".")
        git("commit", "-m", "Initial test catalogs")
        owner.sync_git_repo(skip_push=True)
        owner.create_translations_immediate(force=True)

        english = root / "en_IL" / "tintin.po"
        original_catalog = english.read_bytes()
        original_font = (root / "en_IL/font.ttf").read_bytes()
        english_language = owner.translation_set.get(language_code="en_IL").language
        with override_settings(PEBLATE_COMPONENT=f"{slug}/watch"):
            call_command("peblate_configure_languages")
        owner.refresh_from_db()
        assert not owner.translation_set.filter(language_code="en_IL").exists()
        assert owner.translation_set.filter(language_code="fr_FR").exists()
        assert english.read_bytes() == original_catalog
        assert (root / "en_IL/font.ttf").read_bytes() == original_font
        assert owner.can_add_new_language(None)
        assert (
            owner.add_new_language(english_language, None, show_messages=False) is None
        )
        form = forms.Form()
        form.fields["lang"] = forms.ChoiceField(
            choices=[("", "Choose"), ("en_IL", "English + Hebrew"), ("he_IL", "Hebrew")]
        )
        pebble_translation_choices(form)
        assert list(form.fields["lang"].choices) == [
            ("", "Choose"),
            ("he_IL", "Hebrew"),
        ]
        print(
            "PASS: font-only catalog removed from Weblate, creation excluded, PO and font preserved"
        )
    finally:
        _remove_project(project.pk, None)
