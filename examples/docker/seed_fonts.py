"""Seed Heebo into the disposable local demo via Peblate's upload endpoint."""

from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from peblate.views import mapping_for
from peblate.weblate_adapter import component, language_store

owner = component()
assert owner.vcs == "local" and owner.repo == "local:", (
    "Only the disposable local demo is supported"
)
with owner.repository.lock:
    assert not owner.repository.execute(["remote"], remote_op="none").strip(), (
        "Remove upstream remotes from the disposable demo first"
    )
client = Client()
client.force_login(get_user_model().objects.get(username="admin"))
for slot in ("GOTHIC_18_EXTENDED", "GOTHIC_24_EXTENDED"):
    if any(entry["name"] == slot for entry in mapping_for("he_IL")["fonts"]):
        continue
    response = client.post(
        "/pebble/he_IL/font/",
        {
            "slot": slot,
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
    assert response.status_code == 200, response.content[:500]
    print("Committed demo font:", slot)
store, catalog = language_store("he_IL")
with store.lock:
    print(store.git(["log", "-2", "--oneline"]))
