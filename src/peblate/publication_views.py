"""Publication controls in Weblate; no repository settings or setup jobs."""

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from pebble_language_tools.lang_commands import resolve_font_entries
from pebble_language_tools.release_policy import asset as safe_asset
from pebble_language_tools.release_policy import font_inputs, gaps
from weblate.lang.models import Language

from .models import FontApproval, LanguageJob, PublicationSettings
from .permissions import require_capability
from .publication import evidence, is_maintainer, pack_inputs, pack_locales
from .quality import configure
from .weblate_adapter import component


class PublicationForm(forms.Form):
    enabled = forms.BooleanField(
        required=False, label="Publish language packs when their checks pass"
    )
    minimum_approved_percent = forms.IntegerField(
        min_value=80, max_value=100, initial=80, label="Minimum approved strings (%)"
    )


class FontApprovalForm(forms.Form):
    job = forms.UUIDField(widget=forms.HiddenInput)
    redistribution = forms.BooleanField(
        label="I checked that each custom font's license permits redistribution in language packs and firmware"
    )
    rendering = forms.BooleanField(
        label="I reviewed the rendering and tested this draft on a watch"
    )
    accept_gaps = forms.BooleanField(
        required=False,
        label="I reviewed and accept every missing character listed below",
    )
    accept_unknown = forms.BooleanField(
        required=False,
        label="I checked the required alphabet because its baseline is unknown",
    )
    note = forms.CharField(
        max_length=2000, widget=forms.Textarea(attrs={"rows": 3}), label="Review note"
    )


def require_maintainer(user, owner):
    if not is_maintainer(user, owner):
        raise PermissionDenied(
            "Publication decisions require project management permission."
        )


def inputs_for_user(request, locale):
    owner = component()
    try:
        store, catalog, translation = pack_inputs(owner, locale)
    except ValueError as error:
        raise Http404(str(error)) from error
    if not request.user.has_perm("translation.download", translation or owner):
        raise PermissionDenied("Your role cannot view this language pack.")
    return owner, store, catalog, translation


@never_cache
@require_capability()
def dashboard(request):
    owner = component()
    maintainer = is_maintainer(request.user, owner)
    settings = PublicationSettings.objects.filter(component=owner).first()
    form = PublicationForm(
        initial={
            "enabled": bool(settings and settings.enabled),
            "minimum_approved_percent": settings.minimum_approved_percent
            if settings
            else 80,
        }
    )
    if request.method == "POST":
        require_maintainer(request.user, owner)
        form = PublicationForm(request.POST)
        if form.is_valid():
            if form.cleaned_data["enabled"]:
                configure(owner, request.user)
            PublicationSettings.objects.update_or_create(
                component=owner, defaults=form.cleaned_data
            )
            messages.success(
                request,
                "Publication settings saved in Weblate. Existing string approvals and reviewer permissions are preserved.",
            )
            return redirect("pebble-publication")
    rows = []
    for locale in pack_locales(owner):
        try:
            inputs_for_user(request, locale)
        except PermissionDenied:
            continue
        data = evidence(owner, locale)
        rows.append(
            {
                "locale": locale,
                "url": reverse("pebble-publication-language", args=[locale]),
                "reviewers": data["reviewers"],
                "font_approved": bool(data["fontApproval"]),
                "font_only": data["kind"] == "font-only",
                "approved_percent": data["approvedPercent"],
                "threshold_met": data["approvedPercent"]
                >= data["minimumApprovedPercent"],
            }
        )
    return render(
        request,
        "pebble/publication.html",
        {"owner": owner, "maintainer": maintainer, "form": form, "rows": rows},
    )


@never_cache
@require_capability()
def language(request, locale):
    owner, store, catalog, translation = inputs_for_user(request, locale)
    job = (
        LanguageJob.objects.filter(
            owner=request.user,
            locale=locale,
            operation="build",
            status="succeeded",
            expires_at__gt=timezone.now(),
        )
        .filter(translation=translation, component=owner if not translation else None)
        .order_by("-finished_at")
        .first()
    )
    data = evidence(owner, locale)
    assets = []
    with store.lock:
        mapping = store.mapping(catalog, locale)
        try:
            current_hash = font_inputs(store.path(catalog.parent), mapping)
        except (ValueError, OSError, KeyError):
            current_hash = None
        licenses = sorted(store.path(catalog.parent).glob("LICENSE*"))
        for slot, entry in resolve_font_entries(mapping).items():
            if not entry.get("file"):
                continue
            license_name = entry.get("license") or (
                licenses[0].name if len(licenses) == 1 else None
            )
            assets.append(
                {
                    "slot": slot,
                    "font": entry.get("original_name", entry["file"]),
                    "license": entry.get("license_original_name", license_name),
                    "font_url": reverse(
                        "pebble-publication-asset", args=[locale, slot, "font"]
                    ),
                    "license_url": reverse(
                        "pebble-publication-asset", args=[locale, slot, "license"]
                    )
                    if license_name
                    else None,
                }
            )
    return render(
        request,
        "pebble/publication_language.html",
        {
            "locale": locale,
            "translation": translation,
            "maintainer": is_maintainer(request.user, owner),
            "data": data,
            "assets": assets,
            "job": job,
            "job_current": bool(job and current_hash == job.font_input_hash),
            "missing": [
                {
                    "slot": slot,
                    "characters": " ".join(f"U+{cp:04X} ({chr(cp)})" for cp in points),
                }
                for slot, points in gaps(job.report).items()
            ]
            if job and job.report
            else [],
            "form": FontApprovalForm(initial={"job": job.pk}) if job else None,
            "unknown_baseline": any(
                issue["code"] == "language_baseline_unknown"
                for issue in job.report["issues"]
            )
            if job and job.report
            else False,
            "languages": Language.objects.all().order_by("name")
            if not translation
            else [],
        },
    )


@require_capability()
@require_POST
def check(request, locale):
    from .job_views import submit_job

    owner, _, _, translation = inputs_for_user(request, locale)
    require_maintainer(request.user, owner)
    coverage = ""
    if not translation:
        coverage = request.POST.get("coverage_language", "")
        if not Language.objects.filter(code=coverage).exists():
            return HttpResponse("Choose the language these fonts cover.", status=400)
    with transaction.atomic():
        # Serialize job creation even for font-only packs with no native Translation.
        type(owner).objects.select_for_update().get(pk=owner.pk)
        job, created = LanguageJob.objects.get_or_create(
            owner=request.user,
            translation=translation,
            component=owner if not translation else None,
            locale=locale,
            operation="build",
            status__in=["queued", "running"],
            defaults={"status": "queued", "coverage_language": coverage},
        )
        if created:
            transaction.on_commit(lambda: submit_job(job))
    return redirect("pebble-job", job_id=job.pk)


@require_capability()
@require_POST
def approve(request, locale):
    owner, store, catalog, translation = inputs_for_user(request, locale)
    require_maintainer(request.user, owner)
    form = FontApprovalForm(request.POST)
    if not form.is_valid():
        return HttpResponse(
            "Confirm the license and rendering review and provide a note.", status=400
        )
    job = get_object_or_404(
        LanguageJob,
        pk=form.cleaned_data["job"],
        owner=request.user,
        locale=locale,
        translation=translation,
        component=owner if not translation else None,
        operation="build",
        status="succeeded",
        expires_at__gt=timezone.now(),
    )
    if not job.report or not job.report.get("ok") or not job.font_input_hash:
        return HttpResponse(
            "Build a successful draft before approving its fonts.", status=409
        )
    missing = gaps(job.report)
    unknown = any(
        item["code"] == "language_baseline_unknown" for item in job.report["issues"]
    )
    if (
        missing
        and not form.cleaned_data["accept_gaps"]
        or unknown
        and not form.cleaned_data["accept_unknown"]
    ):
        return HttpResponse(
            "Explicitly accept the displayed coverage gaps and unknown alphabet before approval.",
            status=400,
        )
    with store.lock, transaction.atomic():
        current = font_inputs(
            store.path(catalog.parent), store.mapping(catalog, locale)
        )
        if current != job.font_input_hash:
            return HttpResponse(
                "Fonts changed after this draft was built. Build and review a new draft.",
                status=409,
            )
        FontApproval.objects.update_or_create(
            component=owner,
            locale=locale,
            defaults={
                "approved_by": request.user,
                "input_hash": current,
                "coverage_language": job.coverage_language,
                "accepted_missing_characters": missing,
                "unknown_baseline_accepted": form.cleaned_data["accept_unknown"],
                "note": form.cleaned_data["note"],
            },
        )
    messages.success(
        request,
        "Font, license and rendering approval saved. Later font changes or new coverage gaps require another review.",
    )
    return redirect("pebble-publication-language", locale=locale)


@require_capability()
@require_POST
def revoke(request, locale):
    owner, _, _, _ = inputs_for_user(request, locale)
    require_maintainer(request.user, owner)
    FontApproval.objects.filter(component=owner, locale=locale).delete()
    messages.success(
        request, "Font approval withdrawn. The last published pack remains available."
    )
    return redirect("pebble-publication-language", locale=locale)


@require_capability()
def asset(request, locale, slot, kind):
    _, store, catalog, _ = inputs_for_user(request, locale)
    with store.lock:
        entries = resolve_font_entries(store.mapping(catalog, locale))
        entry = entries.get(slot, {})
        name = (
            entry.get("file" if kind == "font" else "license")
            if kind in ("font", "license")
            else None
        )
        if kind == "license" and entry.get("file") and not name:
            licenses = sorted(store.path(catalog.parent).glob("LICENSE*"))
            name = licenses[0].name if len(licenses) == 1 else None
        if not name:
            raise Http404
        try:
            resource = safe_asset(store.path(catalog.parent), name).open("rb")
        except (ValueError, OSError) as error:
            raise Http404("Font asset is missing or outside this language") from error
        return FileResponse(
            resource,
            as_attachment=True,
            filename=entry.get(
                "original_name" if kind == "font" else "license_original_name", name
            ),
        )
