# SPDX-FileCopyrightText: 2026 Core Devices LLC
# SPDX-License-Identifier: Apache-2.0

"""Exercise native source uploads in an isolated local Weblate component."""

import subprocess
import uuid
from pathlib import Path

import polib
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from weblate.lang.models import Language
from weblate.trans.models import Component, Project

slug = "source-test-" + uuid.uuid4().hex[:8]
project = Project.objects.create(
    slug=slug, name="Disposable source import test " + slug, web="http://localhost/"
)
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
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


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
for locale, language in [("fr_FR", "fr"), ("de_DE", "de")]:
    folder = root / locale
    folder.mkdir()
    catalog = polib.pofile(str(root / "source.pot"))
    catalog.metadata.update(
        {"Language": locale, "Plural-Forms": "nplurals=2; plural=(n != 1);"}
    )
    catalog.find("Keep").msgstr = "Garder" if language == "fr" else "Behalten"
    catalog.find("Remove").msgstr = "Retirer" if language == "fr" else "Entfernen"
    catalog.save(str(folder / "tintin.po"))
    (folder / "lang_map.json").write_text("{}")
    (folder / "font.ttf").write_bytes(b"font-fixture")
git("add", ".")
git("commit", "-m", "Initial test catalogs")
owner.sync_git_repo(skip_push=True)
owner.create_translations_immediate(force=True)

admin = get_user_model().objects.get(username="admin")
unit = owner.translation_set.get(language_code="fr_FR").unit_set.get(source="Keep")
unit.translate(admin, "Conserver", 20, propagate=False)
incoming = polib.POFile()
incoming.metadata = metadata.copy()
incoming.append(polib.POEntry(msgid="Keep"))
incoming.append(polib.POEntry(msgid="New source"))
incoming.append(polib.POEntry(msgid="Open", msgctxt="adjective"))
incoming.append(
    polib.POEntry(
        msgid="%d item",
        msgid_plural="%d items",
        msgstr_plural={0: "", 1: ""},
        flags=["c-format"],
    )
)
client = Client()
url = f"/api/translations/{slug}/watch/en/file/"


def upload():
    return client.post(
        url,
        {
            "method": "source",
            "file": SimpleUploadedFile("pebbleos.pot", str(incoming).encode()),
        },
    )


assert upload().status_code in (401, 403)
client.force_login(admin)
response = upload()
assert response.status_code == 200, response.content[:500]
assert (root / "source.pot").read_text() == str(incoming)
assert "source.pot" in git("ls-files").splitlines()
for locale in ("fr_FR", "de_DE"):
    catalog = polib.pofile(str(root / locale / "tintin.po"))
    assert catalog.find("Keep").msgstr == (
        "Conserver" if locale == "fr_FR" else "Behalten"
    )
    assert catalog.find("New source") is not None
    assert catalog.find("Open", msgctxt="adjective") is not None
    assert catalog.find("%d item").msgid_plural == "%d items"
    assert (root / locale / "font.ttf").read_bytes() == b"font-fixture"
    assert (root / locale / "lang_map.json").read_text() == "{}"
assert upload().status_code == 200
response = client.post(f"/new-lang/{slug}/watch/", {"lang": "it"})
assert response.status_code == 302, response.content[:500]
catalog = polib.pofile(str(root / "it_IT/tintin.po"))
assert catalog.find("New source") is not None
assert catalog.find("Keep").msgstr == ""
print(
    "PASS: native source API, authentication, saved translations, contexts, plurals, repeated upload and regional language creation"
)
project.delete()
