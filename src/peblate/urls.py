# SPDX-FileCopyrightText: 2026 Core Devices LLC
# SPDX-License-Identifier: Apache-2.0

from django.urls import include, path

from . import auth_views, job_views, setup_views, views
from .weblate_adapter import project_language_setup

urlpatterns = [
    path("accounts/login/", auth_views.pebble_login, name="login"),
    path(
        "accounts/login/existing/",
        auth_views.ExistingLoginView.as_view(),
        name="pebble-existing-login",
    ),
    path("accounts/login/pebble/", auth_views.pebble_begin),
    path("accounts/register/", auth_views.pebble_register, name="register"),
    path("accounts/complete/pebble/", auth_views.pebble_complete),
    path("new-lang/<str:project>/<str:component>/", setup_views.language_setup),
    path("pebble/setup/prepare/", setup_views.prepare, name="pebble-setup-prepare"),
    path(
        "pebble/setup/preview/<str:slot>/",
        setup_views.preview,
        name="pebble-setup-preview",
    ),
    path("new-lang/<str:project>/", project_language_setup),
    path("pebble/setup/coverage/", views.setup_coverage, name="pebble-setup-coverage"),
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
