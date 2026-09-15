# SPDX-FileCopyrightText: 2026 Core Devices LLC
# SPDX-License-Identifier: Apache-2.0

"""Prepare a disposable service seed; never modifies the translation catalogs."""

import os
import secrets
import shutil
import subprocess
from pathlib import Path

import polib

HERE = Path(__file__).resolve().parents[2]
ROOT = Path(
    os.environ.get("TRANSLATIONS_PATH", HERE.parent / "pebbleos-translations")
).resolve()
if not (HERE / ".env").exists():
    (HERE / ".env").write_text(
        f"DATABASE_PASSWORD={secrets.token_urlsafe(24)}\nADMIN_PASSWORD={secrets.token_urlsafe(18)}\n"
    )
    (HERE / ".env").chmod(0o600)
seed = HERE / "runtime/seed"
if not (seed / ".git").exists():
    (seed / "fr_FR").mkdir(parents=True, exist_ok=True)
    (seed / "he_IL").mkdir()
    shutil.copy(ROOT / "fr_FR/tintin.po", seed / "fr_FR/tintin.po")
    source = polib.pofile(str(ROOT / "fr_FR/tintin.po"))
    source.metadata["Language"] = "en"
    source.metadata["Plural-Forms"] = "nplurals=2; plural=(n != 1);"
    for entry in source:
        entry.msgstr = ""
        entry.msgstr_plural = {key: "" for key in entry.msgstr_plural}
        entry.flags = [flag for flag in entry.flags if flag != "fuzzy"]
    source.save(str(seed / "source.pot"))
    source.metadata["Language"] = "he_IL"
    source.metadata["Plural-Forms"] = "nplurals=2; plural=(n != 1);"
    examples = {"Settings": "הגדרות", "Music": "מוזיקה", "Battery": "סוללה"}
    for entry in source:
        entry.msgstr = examples.get(entry.msgid, "")
    source.save(str(seed / "he_IL/tintin.po"))
    for args in (
        ["init", "-b", "main"],
        ["add", "."],
        [
            "-c",
            "user.name=Pebble prototype",
            "-c",
            "user.email=prototype@localhost.test",
            "commit",
            "-m",
            "Seed local Weblate trial",
        ],
    ):
        subprocess.run(["git", "-C", str(seed), *args], check=True)
print("Prepared local seed and .env. No upstream Git remote is configured.")

fixtures = Path(__file__).resolve().parent / "fixtures"
fixtures.mkdir(exist_ok=True)
for name in ("Heebo-Regular.ttf", "LICENSE.Heebo.txt"):
    shutil.copy(ROOT / "en_IL" / name, fixtures / name)
