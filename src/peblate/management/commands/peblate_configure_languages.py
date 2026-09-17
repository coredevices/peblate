# SPDX-FileCopyrightText: 2026 Core Devices LLC
# SPDX-License-Identifier: Apache-2.0

import re

from django.core.management.base import BaseCommand

from peblate.language_policy import TRANSLATION_LANGUAGE_FILTER
from peblate.weblate_adapter import component


class Command(BaseCommand):
    help = "Exclude English font-only packs from the configured translation component."

    def handle(self, *args, **options):
        owner = component()
        with owner.repository.lock:
            for translation in owner.translation_set.exclude(
                pk=owner.source_translation.pk
            ):
                if re.match(r"(?i)^en(?:[_@-]|$)", translation.language_code):
                    translation.commit_pending(
                        "peblate-font-only", None, skip_push=True
                    )
            owner.language_regex = TRANSLATION_LANGUAGE_FILTER
            owner.save()
            owner.create_translations_immediate(force=True)
        self.stdout.write(
            self.style.SUCCESS(
                "English font-only catalogs excluded from Weblate; repository files retained."
            )
        )
