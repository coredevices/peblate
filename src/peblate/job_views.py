# SPDX-FileCopyrightText: 2026 Core Devices LLC
# SPDX-License-Identifier: Apache-2.0

"""Queue, inspect, and download permission-scoped background jobs."""

import logging

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import FileResponse, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from .models import LanguageJob
from .permissions import capabilities, require_capability
from .tasks import expire_stalled_jobs, job_folder, run_language_job
from .weblate_adapter import enabled_component, translation_for_code


def job_data(job):
    url = reverse("pebble-job", args=[job.pk])
    return {
        "id": str(job.pk),
        "status": job.status,
        "phase": job.phase,
        "operation": job.operation,
        "locale": job.locale,
        "report": job.report,
        "error": job.error,
        "snapshot_at": job.snapshot_at.isoformat() if job.snapshot_at else None,
        "source_revision": job.source_revision,
        "status_url": url + "?format=json",
        "page_url": url,
        "translation_url": job.translation.get_translate_url(),
        "retry_url": reverse("pebble-validate", args=[job.translation.language_code]),
        "download_url": reverse("pebble-job-download", args=[job.pk])
        if job.status == "succeeded"
        and job.operation == "build"
        and job.report
        and job.report.get("ok")
        else None,
    }


@never_cache
@require_capability("validate")
@require_POST
def enqueue(request, code):
    operation = request.POST.get("action", "validate")
    if operation not in ("validate", "build"):
        return HttpResponse(
            "Choose check or build.", status=400, content_type="text/plain"
        )
    translation = translation_for_code(code)
    expire_stalled_jobs()
    with transaction.atomic():
        job, created = LanguageJob.objects.get_or_create(
            owner=request.user,
            translation=translation,
            operation=operation,
            status__in=["queued", "running"],
            defaults={"status": "queued"},
        )
        if created:

            def submit():
                try:
                    run_language_job.apply_async(args=[str(job.pk)], retry=False)
                except Exception:
                    logging.getLogger(__name__).exception(
                        "Could not enqueue Peblate job %s", job.pk
                    )
                    LanguageJob.objects.filter(pk=job.pk, status="queued").update(
                        status="failed",
                        phase="Failed",
                        error="The job queue is unavailable. Retry once the worker service is available.",
                        finished_at=timezone.now(),
                    )

            transaction.on_commit(submit)
    job.refresh_from_db()
    if request.POST.get("format") == "json":
        return JsonResponse(job_data(job), status=202)
    return redirect("pebble-job", job_id=job.pk)


def authorized_job(request, job_id):
    job = get_object_or_404(
        LanguageJob.objects.select_related("translation__component__project"),
        pk=job_id,
        owner=request.user,
    )
    if (
        job.translation.component.full_slug != enabled_component()
        or not capabilities(request.user, job.translation)["validate"]
    ):
        raise PermissionDenied("Your Weblate permissions no longer allow this job.")
    return job


@never_cache
@login_required
def job_status(request, job_id):
    expire_stalled_jobs()
    job = authorized_job(request, job_id)
    if job.expires_at <= timezone.now():
        return HttpResponse("This result has expired. Start a new job.", status=410)
    data = job_data(job)
    if request.GET.get("format") == "json":
        return JsonResponse(data)
    return render(request, "pebble/job.html", {"job": data})


@never_cache
@login_required
def download(request, job_id):
    job = authorized_job(request, job_id)
    if job.expires_at <= timezone.now():
        return HttpResponse("This draft has expired. Build a new draft.", status=410)
    if not job_data(job)["download_url"]:
        return HttpResponse("The draft is not ready.", status=409)
    path = job_folder(job.pk) / "dist" / (job.locale + ".pbl")
    if not path.is_file():
        return HttpResponse(
            "This draft is no longer available. Build a new draft.", status=410
        )
    return FileResponse(
        path.open("rb"),
        as_attachment=True,
        filename=job.locale + ".pbl",
        content_type="application/octet-stream",
    )
