# SPDX-FileCopyrightText: 2026 Core Devices LLC
# SPDX-License-Identifier: Apache-2.0

"""Durable language-job status and ownership of uploaded font assignments."""

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
    translation = models.ForeignKey(
        "trans.Translation", on_delete=models.CASCADE, null=True
    )
    component = models.ForeignKey(
        "trans.Component", on_delete=models.CASCADE, null=True
    )
    font_input_hash = models.CharField(max_length=64, blank=True)
    coverage_language = models.CharField(max_length=80, blank=True)
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


class FontOwnership(models.Model):
    """Uploader of the current font assignment; repository metadata is not authority."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    translation = models.ForeignKey("trans.Translation", on_delete=models.CASCADE)
    slot = models.CharField(max_length=80)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True
    )
    fingerprint = models.CharField(max_length=64)

    class Meta:
        constraints = (
            models.UniqueConstraint(
                fields=["translation", "slot"], name="peblate_font_assignment"
            ),
        )


class PublicationSettings(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    component = models.OneToOneField("trans.Component", on_delete=models.CASCADE)
    enabled = models.BooleanField(default=False)
    minimum_approved_percent = models.PositiveSmallIntegerField(default=80)


class FontApproval(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    component = models.ForeignKey("trans.Component", on_delete=models.CASCADE)
    locale = models.CharField(max_length=80)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True
    )
    approved_at = models.DateTimeField(auto_now=True)
    input_hash = models.CharField(max_length=64)
    coverage_language = models.CharField(max_length=80, blank=True)
    accepted_missing_characters = models.JSONField(default=dict)
    unknown_baseline_accepted = models.BooleanField(default=False)
    note = models.TextField()

    class Meta:
        constraints = (
            models.UniqueConstraint(
                fields=["component", "locale"], name="peblate_font_approval"
            ),
        )
