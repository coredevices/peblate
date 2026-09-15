# SPDX-FileCopyrightText: 2026 Core Devices LLC
# SPDX-License-Identifier: Apache-2.0

"""Durable job status for language checks and draft packs."""

import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


def expires_at():
    return timezone.now() + timedelta(days=1)


class LanguageJob(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    translation = models.ForeignKey("trans.Translation", on_delete=models.CASCADE)
    operation = models.CharField(max_length=10)
    status = models.CharField(max_length=10, default="queued")
    phase = models.CharField(max_length=120, default="Waiting for a worker")
    locale = models.CharField(max_length=80, blank=True)
    source_revision = models.CharField(max_length=64, blank=True)
    snapshot_at = models.DateTimeField(null=True)
    report = models.JSONField(null=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True)
    finished_at = models.DateTimeField(null=True)
    expires_at = models.DateTimeField(default=expires_at)

    class Meta:
        constraints = (
            models.UniqueConstraint(
                fields=["owner", "translation", "operation"],
                condition=Q(status__in=["queued", "running"]),
                name="peblate_one_active_job",
            ),
        )
