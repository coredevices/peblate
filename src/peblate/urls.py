# SPDX-FileCopyrightText: 2026 Core Devices LLC
# SPDX-License-Identifier: Apache-2.0

from django.urls import include, path

from . import job_views, views

urlpatterns = [
    path("pebble/jobs/<uuid:job_id>/", job_views.job_status, name="pebble-job"),
    path(
        "pebble/jobs/<uuid:job_id>/download/",
        job_views.download,
        name="pebble-job-download",
    ),
    path("pebble/", views.home, name="pebble-home"),
    path("pebble/<str:code>/", views.language, name="pebble-language"),
    path("pebble/<str:code>/font/", views.upload_font, name="pebble-upload"),
    path("pebble/<str:code>/font/<str:slot>/", views.font_file, name="pebble-font"),
    path(
        "pebble/<str:code>/font/<str:slot>/pbf/",
        views.preview_font,
        name="pebble-font-pbf",
    ),
    path("pebble/<str:code>/validate/", job_views.enqueue, name="pebble-validate"),
    path("", include("weblate.urls")),
]
