# SPDX-FileCopyrightText: 2026 Core Devices LLC
# SPDX-License-Identifier: Apache-2.0

"""Exercise job lifecycle and isolation against the installed Weblate extension."""

import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import polib
from django.contrib.auth import get_user_model
from django.db import close_old_connections
from django.test import Client, override_settings
from django.utils import timezone
from weblate.vcs.git import LocalRepository

from peblate import tasks
from peblate.asset_store import AssetStore
from peblate.models import LanguageJob
from peblate.weblate_adapter import component, translation_for_code

owner = component()
assert owner.vcs == "local" and owner.repo == "local:"
user = get_user_model().objects.get(username="peblate-translator")
client = Client()
client.force_login(user)
created = []


def queue(client=client):
    response = client.post(
        "/pebble/he_IL/validate/", {"action": "build", "format": "json"}
    )
    assert response.status_code == 202, response.content[:500]
    result = response.json()
    created.append(result["id"])
    return result


with tempfile.TemporaryDirectory(prefix="peblate-jobs-test-") as temp:
    root = Path(temp)
    clone = root / "repo"
    with owner.repository.lock:
        subprocess.run(
            ["git", "clone", "--no-local", owner.full_path, str(clone)],
            check=True,
            capture_output=True,
        )
    repository = LocalRepository(str(clone), local=True)
    store = AssetStore(
        clone, lambda args: repository.execute(args, remote_op="none"), repository.lock
    )

    def isolated_store(code):
        return store, Path(translation_for_code(code).filename)

    with (
        override_settings(PEBLATE_CACHE_ROOT=str(root / "cache")),
        patch("peblate.tasks.language_store", isolated_store),
        patch("peblate.tasks.saved_catalog"),
        patch("peblate.job_views.run_language_job.apply_async") as publish,
    ):

        def simultaneous(_):
            close_old_connections()
            try:
                local = Client()
                local.force_login(get_user_model().objects.get(pk=user.pk))
                return queue(local)
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = list(pool.map(simultaneous, range(2)))
        assert first["id"] == second["id"] and publish.call_count == 1
        assert (
            client.get("/pebble/jobs/" + first["id"] + "/download/").status_code == 409
        )
        stranger = Client()
        stranger.force_login(get_user_model().objects.get(username="peblate-reviewer"))
        assert stranger.get(first["status_url"]).status_code == 404
        assert (
            stranger.get("/pebble/jobs/" + first["id"] + "/download/").status_code
            == 404
        )
        original_compile = tasks.compile_snapshot

        def edit_after_snapshot(job, snapshot):
            po_path = clone / "he_IL/tintin.po"
            catalog = polib.pofile(str(po_path))
            catalog.find("Music").msgstr = "בדיקה"
            catalog.save(str(po_path))
            assert (snapshot / "he_IL/tintin.po").read_bytes() != po_path.read_bytes()
            return original_compile(job, snapshot)

        with patch("peblate.tasks.compile_snapshot", edit_after_snapshot):
            tasks.run_language_job.run(first["id"])
        result = client.get(first["status_url"]).json()
        assert result["status"] == "succeeded" and result["download_url"], result
        assert client.get(first["page_url"]).status_code == 200
        pack = b"".join(client.get(result["download_url"]).streaming_content)
        assert pack[:4] == b"\x15\0\0\0"
        tasks.run_language_job.run(first["id"])
        assert b"".join(client.get(result["download_url"]).streaming_content) == pack
        second = queue()
        tasks.run_language_job.run(second["id"])
        newer = client.get(second["status_url"]).json()
        assert newer["download_url"], newer
        assert b"".join(client.get(newer["download_url"]).streaming_content) != pack
        with patch("peblate.job_views.capabilities", return_value={"validate": False}):
            assert client.get(first["status_url"]).status_code == 403
            assert client.get(result["download_url"]).status_code == 403
        denied = queue()
        with patch("peblate.tasks.capabilities", return_value={"validate": False}):
            tasks.run_language_job.run(denied["id"])
        assert client.get(denied["status_url"]).json()["status"] == "failed"
        failed = queue()
        with patch(
            "peblate.tasks.compile_snapshot",
            side_effect=subprocess.TimeoutExpired("font", 90),
        ):
            tasks.run_language_job.run(failed["id"])
        assert "too long" in client.get(failed["status_url"]).json()["error"]
        retry = queue()
        assert retry["id"] != failed["id"]
        LanguageJob.objects.filter(pk=retry["id"]).update(
            status="running", started_at=timezone.now() - timedelta(minutes=7)
        )
        assert client.get(retry["status_url"]).json()["status"] == "failed"
        publish.side_effect = ConnectionError("test broker offline")
        unavailable = queue()
        assert (
            unavailable["status"] == "failed"
            and "queue is unavailable" in unavailable["error"]
        )
        LanguageJob.objects.filter(pk=first["id"]).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        assert client.get(result["download_url"]).status_code == 410
        tasks.cleanup_jobs.run()
        assert not tasks.job_folder(first["id"]).exists()
        assert not LanguageJob.objects.filter(pk=first["id"]).exists()
LanguageJob.objects.filter(pk__in=created).delete()
print(
    "PASS: concurrent dedup, ownership, permission rechecks, fixed snapshots, duplicate delivery, retries, timeouts, broker failure, expiry and cleanup"
)
