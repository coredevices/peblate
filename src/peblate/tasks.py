# SPDX-FileCopyrightText: 2026 Core Devices LLC
# SPDX-License-Identifier: Apache-2.0

"""Run pack tools on Weblate's existing Celery workers."""

import json
import logging
import shutil
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

from celery.exceptions import SoftTimeLimitExceeded
from django.conf import settings
from django.utils import timezone
from weblate.utils.celery import app

from .models import LanguageJob
from .permissions import capabilities
from .weblate_adapter import enabled_component, language_store, saved_catalog

logger = logging.getLogger(__name__)


def job_folder(job_id):
    return Path(settings.PEBLATE_CACHE_ROOT) / "jobs" / str(job_id)


def expire_stalled_jobs():
    LanguageJob.objects.filter(
        status="running", started_at__lt=timezone.now() - timedelta(minutes=6)
    ).update(
        status="failed",
        phase="Failed",
        error="The worker did not finish this job. Retry to start a new job.",
        finished_at=timezone.now(),
    )
    LanguageJob.objects.filter(
        status="queued", created_at__lt=timezone.now() - timedelta(minutes=15)
    ).update(
        status="failed",
        phase="Failed",
        error="No worker picked up this job. Check the worker is running, then retry.",
        finished_at=timezone.now(),
    )


def set_phase(job, phase):
    LanguageJob.objects.filter(pk=job.pk).update(phase=phase)


def snapshot_inputs(job, root):
    translation = job.translation
    if (
        translation.component.full_slug != enabled_component()
        or not capabilities(job.owner, translation)["validate"]
    ):
        raise PermissionError("Your permission to build this language was removed.")
    saved_catalog(translation)
    store, catalog = language_store(translation.language_code)
    job.locale = catalog.parent.name
    with store.lock:
        store.ensure_mapping(catalog, job.locale)
        store.snapshot(catalog, job.locale, root / job.locale)
        job.source_revision = store.git(["rev-parse", "HEAD"]).strip()
        job.snapshot_at = timezone.now()
    job.save(update_fields=["locale", "source_revision", "snapshot_at"])


def compile_snapshot(job, root):
    command = [sys.executable, "-m", "pebble_language_tools.lang", "--root", str(root)]
    set_phase(job, "Checking translations and font coverage")
    result = subprocess.run(
        command + ["check_lang", "--lang", job.locale, "--json"],
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError("The validation tool could not run.")
    report = json.loads(result.stdout)
    if job.operation == "build" and report["ok"]:
        set_phase(job, "Building the draft language pack")
        subprocess.run(
            command
            + ["pack_lang", "--lang", job.locale, "--output", str(root / "dist")],
            capture_output=True,
            text=True,
            timeout=90,
            check=True,
        )
    return report


@app.task(
    name="peblate.tasks.run_language_job",
    soft_time_limit=240,
    time_limit=270,
    acks_late=True,
    trail=False,
)
def run_language_job(job_id):
    if not LanguageJob.objects.filter(pk=job_id, status="queued").update(
        status="running",
        phase="Taking a snapshot of saved translations and fonts",
        started_at=timezone.now(),
    ):
        return
    job = LanguageJob.objects.select_related(
        "owner", "translation__component__project"
    ).get(pk=job_id)
    root = job_folder(job.pk)
    try:
        root.mkdir(parents=True, exist_ok=True)
        snapshot_inputs(job, root)
        report = compile_snapshot(job, root)
        LanguageJob.objects.filter(pk=job.pk, status="running").update(
            status="succeeded",
            phase="Ready" if report["ok"] else "Needs attention",
            report=report,
            finished_at=timezone.now(),
        )
    except (subprocess.TimeoutExpired, SoftTimeLimitExceeded):
        LanguageJob.objects.filter(pk=job.pk).update(
            status="failed",
            phase="Failed",
            error="The font checks or build took too long. Try a smaller font or retry the job.",
            finished_at=timezone.now(),
        )
    except (ValueError, PermissionError) as error:
        LanguageJob.objects.filter(pk=job.pk).update(
            status="failed",
            phase="Failed",
            error=str(error),
            finished_at=timezone.now(),
        )
    except Exception:
        logger.exception("Peblate job %s failed", job.pk)
        LanguageJob.objects.filter(pk=job.pk).update(
            status="failed",
            phase="Failed",
            error="The job could not finish. Retry, or ask the administrator to check the worker logs.",
            finished_at=timezone.now(),
        )
    finally:
        # Only the report and finished draft need to remain available for download.
        for child in root.iterdir() if root.exists() else []:
            if child.name != "dist" and child.is_dir():
                shutil.rmtree(child, ignore_errors=True)


@app.task(name="peblate.tasks.cleanup_jobs", trail=False)
def cleanup_jobs():
    expire_stalled_jobs()
    expired = list(
        LanguageJob.objects.filter(expires_at__lt=timezone.now()).values_list(
            "pk", flat=True
        )
    )
    for job_id in expired:
        shutil.rmtree(job_folder(job_id), ignore_errors=True)
    LanguageJob.objects.filter(pk__in=expired).delete()
    # Also remove files left behind if an account or translation was deleted.
    folder = Path(settings.PEBLATE_CACHE_ROOT) / "jobs"
    for child in folder.iterdir() if folder.exists() else []:
        if (
            child.is_dir()
            and timezone.now().timestamp() - child.stat().st_mtime > 86400
        ):
            shutil.rmtree(child, ignore_errors=True)
