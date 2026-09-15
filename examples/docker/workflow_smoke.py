"""Exercise the native translator-to-reviewer workflow on the Italian demo string."""

import json
import re
import time
from pathlib import Path

from django.test import Client
from django.test.utils import setup_test_environment

from peblate.weblate_adapter import component

setup_test_environment()
credentials = json.loads(Path("/app/data/peblate-demo-accounts.json").read_text())
owner = component()
assert owner.repo == "local:" and owner.vcs == "local"
client = Client()
assert client.login(
    username="peblate-translator", password=credentials["peblate-translator"]
)
if not owner.translation_set.filter(language__code="it").exists():
    response = client.post("/new-lang/pebbleos/watch/", {"lang": "it"})
    assert response.status_code == 302
translation = owner.translation_set.get(language__code="it")
assert translation.filename == "it_IT/tintin.po"
if not translation.unit_set.exists():
    owner.create_translations_immediate(force=True)
unit = translation.unit_set.get(source="Music")
assert unit.target in ("", "Musica"), "Preserve any manually edited demo translation"
url = translation.get_translate_url() + "?checksum=" + unit.checksum


def save(client, review=False):
    page = client.get(url)
    assert page.status_code == 200
    form = page.context["form"]
    assert "target" in form.fields
    data = {
        form.add_prefix(name): form[name].value()
        for name in form.fields
        if name not in ("target", "fuzzy", "review") and form[name].value() is not None
    }
    target_name = re.search(r'name="([^"]+)"', str(form["target"])).group(1)
    data[target_name] = "Musica"
    data["save-stay"] = "1"
    if review:
        data[form.add_prefix("review")] = "30"
    response = client.post(url, data)
    assert response.status_code in (200, 302), response.status_code
    unit.refresh_from_db()
    assert unit.target == "Musica", (unit.target, response.content[:200])
    return unit.state


if not unit.target:
    print("Translator saved Italian Music:", save(client))
if unit.state != 30:
    assert save(client, review=True) != 30, "Translator must not approve strings"
reviewer = Client()
assert reviewer.login(
    username="peblate-reviewer", password=credentials["peblate-reviewer"]
)
state = save(reviewer, review=True)
assert state == 30, state
print("Reviewer approved Italian Music; native state:", state)
response = client.post("/pebble/it_IT/validate/", {"action": "build", "format": "json"})
assert response.status_code == 202, response.content[:300]
job = response.json()
deadline = time.monotonic() + 60
while job["status"] in ("queued", "running") and time.monotonic() < deadline:
    time.sleep(1)
    job = client.get(job["status_url"]).json()
assert job["status"] == "succeeded" and job["download_url"], job
response = client.get(job["download_url"])
assert response.status_code == 200
assert "it_IT.pbl" in response["Content-Disposition"]
assert b"".join(response.streaming_content)[:4] == b"\x15\0\0\0"
print(
    "Real Celery worker built it_IT.pbl from the reviewed regional catalog", job["id"]
)
