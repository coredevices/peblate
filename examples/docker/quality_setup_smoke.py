"""Idempotent native quality setup; rollback database and remove new local glossary."""

import shutil
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import Client

from peblate.quality import configure
from peblate.weblate_adapter import component

assert settings.SITE_DOMAIN == "localhost:8088", "Run only in the local prototype"
owner = component()
assert owner.vcs == "local" and not owner.project.glossaries
admin = get_user_model().objects.get(username="admin")
folder = None
try:
    with (
        transaction.atomic(),
        patch("celery.app.task.Task.apply_async"),
        patch("weblate.trans.models.Component.queue_background_task"),
    ):
        source = owner.source_translation.unit_set.filter(source="Music").get()
        before_source_flags = source.extra_flags
        before = owner.check_flags
        client = Client()
        client.force_login(admin)
        assert client.get("/pebble/publication/").status_code == 200
        owner.refresh_from_db()
        assert owner.check_flags == before
        configure(owner, admin)
        owner.refresh_from_db()
        source.refresh_from_db()
        assert source.extra_flags == before_source_flags
        assert "check-glossary" in owner.check_flags
        glossary = owner.project.component_set.get(slug="pebble-glossary")
        folder = Path(glossary.full_path)
        assert glossary.is_glossary and glossary.vcs == "local"
        assert glossary.source_translation.unit_set.count() == 3
        configure(owner, admin)
        assert glossary.source_translation.unit_set.count() == 3
        assert set(
            glossary.source_translation.unit_set.values_list("source", flat=True)
        ) == {"Timeline", "Quick View", "watchface"}
        term = glossary.source_translation.unit_set.get(source="watchface")
        term.explanation = "Maintainer's wording"
        term.save(update_fields=["explanation"])
        configure(owner, admin)
        term.refresh_from_db()
        assert term.explanation == "Maintainer's wording"
        transaction.set_rollback(True)
finally:
    if folder and folder.resolve().is_relative_to(Path("/app/data/vcs").resolve()):
        shutil.rmtree(folder, ignore_errors=True)
print(
    "PASS: read-only page, unchanged string flags, native glossary creation, editable terms and idempotent setup"
)
