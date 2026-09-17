# SPDX-FileCopyrightText: 2026 Core Devices LLC
# SPDX-License-Identifier: Apache-2.0

"""Run with `weblate shell < /prototype/bootstrap.py` after first startup."""

import shutil
from pathlib import Path

from peblate.language_policy import TRANSLATION_LANGUAGE_FILTER
from weblate.lang.models import Language
from weblate.trans.models import Component, Project

project, _ = Project.objects.get_or_create(
    slug="pebbleos",
    defaults={"name": "PebbleOS · local trial", "web": "http://localhost:8088/pebble/"},
)
component, created = Component.objects.get_or_create(
    project=project,
    slug="watch",
    defaults={
        "name": "Watch strings",
        "repo": "local:",
        "vcs": "local",
        "branch": "main",
        "filemask": "*/tintin.po",
        "language_regex": TRANSLATION_LANGUAGE_FILTER,
        "language_code_style": "posix_long",
        "inherit_language_code_style": False,
        "file_format": "po",
        "new_base": "source.pot",
        "template": "",
        "new_lang": "add",
        "inherit_new_lang": False,
        "source_language": Language.objects.get(code="en"),
        "license": "Apache-2.0",
    },
)
Component.objects.filter(pk=component.pk).update(
    repo="local:", vcs="local", language_regex=TRANSLATION_LANGUAGE_FILTER
)
component = Component.objects.get(pk=component.pk)
if not Path(component.full_path).exists():
    shutil.copytree("/seed", component.full_path)
component.sync_git_repo(skip_push=True)
component.create_translations_immediate(force=True)
print("Project:", project.get_absolute_url())
print(
    "Translations:",
    list(component.translation_set.values_list("language_code", flat=True)),
)
