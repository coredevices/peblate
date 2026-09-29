"""Private, expiring font drafts reviewed before native language creation."""

import json
import shutil
import subprocess
import sys
import uuid
from contextvars import ContextVar
from pathlib import Path

from django.conf import settings
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.templatetags.static import static
from django.urls import reverse
from django.views.decorators.http import require_POST
from weblate.lang.models import Language
from weblate.trans.forms import get_new_component_language_form
from weblate.trans.views.basic import new_language
from weblate.vcs.base import RepositoryError

from .permissions import require_capability
from .setup_fonts import TEXT_SLOTS, font_packs, requirements, reuse_pack
from .views import SLOTS
from .weblate_adapter import component, component_store, enabled_component

creation_draft = ContextVar("peblate_creation_draft", default=None)


def selection(request, code, *, available=True):
    owner = component()
    if not request.user.has_perm(
        "translation.add", owner
    ) or not owner.can_add_new_language(request.user):
        raise PermissionDenied
    selected = get_object_or_404(Language, code=code)
    # RestrictedLanguageForm expects a single value, owner forms a list.
    from django.http import QueryDict

    data = QueryDict(mutable=True)
    data.setlist("lang", [code])
    form = get_new_component_language_form(request, owner)(request.user, owner, data)
    if available and not form.is_valid():
        raise PermissionDenied("This language is not available for creation.")
    from .language_policy import translation_language_allowed

    if not translation_language_allowed(code):
        raise Http404
    return owner, selected


def draft_root():
    return Path(settings.PEBLATE_CACHE_ROOT) / "setup"


def read_draft(request, token, code):
    try:
        data = signing.loads(token, salt="peblate-setup", max_age=86400)
        if (
            data["user"] != request.user.pk
            or data["language"] != code
            or data["component"] != enabled_component()
        ):
            raise ValueError
        folder = draft_root() / str(uuid.UUID(data["id"]))
        if not folder.is_dir():
            raise ValueError
        return folder
    except (signing.BadSignature, ValueError, KeyError, TypeError):
        raise ValueError(
            "This font review expired. Prepare and review the fonts again."
        ) from None


def font_permissions(request, owner, selected):
    from weblate.trans.models import Translation

    target = Translation(
        component=owner, language=selected, language_code=selected.code
    )
    if not all(
        request.user.has_perm(perm, target)
        for perm in ("translation.download", "unit.edit", "upload.perform")
    ):
        raise PermissionDenied(
            "Your Weblate role cannot supply fonts for this language."
        )


@require_capability()
@require_POST
def prepare(request):
    code = request.POST.get("language", "")
    owner, selected = selection(request, code)
    font_permissions(request, owner, selected)
    folder = draft_root() / str(uuid.uuid4())
    folder.mkdir(parents=True)
    try:
        pack = request.POST.get("pack")
        if pack:
            store = component_store(owner)
            with store.lock:
                if pack not in {item["code"] for item in font_packs(store.root, code)}:
                    raise ValueError("Choose a suggested font pack.")
                entries = reuse_pack(store.root, pack, folder)
        else:
            from .font_upload import validate_upload

            regular, license_data, regular_name, license_name = validate_upload(
                request.FILES.get("font"), request.FILES.get("license")
            )
            (folder / "regular.ttf").write_bytes(regular)
            (folder / "license.txt").write_bytes(license_data)
            bold = request.FILES.get("bold")
            if bold:
                bold_data, _, bold_name, _ = validate_upload(
                    bold, None, license_data=license_data
                )
                (folder / "bold.ttf").write_bytes(bold_data)
            entries = [
                {
                    "name": slot,
                    "file": "bold.ttf" if bold and "BOLD" in slot else "regular.ttf",
                    "license": "license.txt",
                    "extended": True,
                    "original_name": bold_name
                    if bold and "BOLD" in slot
                    else regular_name,
                    "license_original_name": license_name,
                }
                for slot in TEXT_SLOTS
            ]
        (folder / "fonts.json").write_text(json.dumps(entries))
        result = subprocess.run(
            [sys.executable, "-m", "peblate.setup_fonts", str(folder), code],
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
        if result.returncode:
            detail = (
                result.stderr.strip().splitlines()[-1]
                if result.stderr.strip()
                else "Font compilation failed."
            )
            raise ValueError(detail.removeprefix("ValueError: "))
        report = json.loads((folder / "report.json").read_text())
        token = signing.dumps(
            {
                "id": folder.name,
                "user": request.user.pk,
                "language": code,
                "component": enabled_component(),
            },
            salt="peblate-setup",
        )
        return JsonResponse(
            {
                **report,
                "token": token,
                "styles": [
                    {
                        **style,
                        "label": dict(SLOTS)[style["name"]],
                        "base_url": static(
                            "pebble/renderer/"
                            + style["name"].removesuffix("_EXTENDED")
                            + ".pbf"
                        ),
                        "preview_url": reverse(
                            "pebble-setup-preview", args=[style["name"]]
                        ),
                    }
                    for style in report["styles"]
                ],
            }
        )
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        shutil.rmtree(folder, ignore_errors=True)
        message = (
            "Font preparation took too long. Try a smaller font."
            if isinstance(error, subprocess.TimeoutExpired)
            else str(error)
        )
        return HttpResponse(message, status=400, content_type="text/plain")


@require_capability()
@require_POST
def preview(request, slot):
    code = request.POST.get("language", "")
    owner, selected = selection(request, code)
    font_permissions(request, owner, selected)
    if slot not in TEXT_SLOTS:
        raise Http404
    try:
        folder = read_draft(request, request.POST.get("token", ""), code)
    except ValueError as error:
        return HttpResponse(str(error), status=400, content_type="text/plain")
    return FileResponse(
        (folder / (slot + ".pbf")).open("rb"), content_type="application/octet-stream"
    )


def install_creation_fonts(sender, translation, **kwargs):
    draft = creation_draft.get()
    if (
        not draft
        or translation.component_id != draft["component"]
        or translation.language.code != draft["language"]
    ):
        return
    store = component_store(translation.component)
    catalog = Path(translation.get_filename()).relative_to(store.root)
    store.install_prepared(catalog, draft["folder"], language=draft["language"])


def language_setup(request, project, component):
    path = [project, component]
    if "/".join(path) != enabled_component() or request.method != "POST":
        return new_language(request, path=path)
    codes = request.POST.getlist("lang")
    if len(codes) != 1:
        return HttpResponse(
            "Set up one language at a time so you can review its fonts.",
            status=400,
            content_type="text/plain",
        )
    owner, selected = selection(request, codes[0])
    _, required = requirements(selected.code)
    from .font_guidance import baseline_coverage

    coverage = baseline_coverage(selected.code)
    needs_fonts = coverage and any(coverage[name] for name in TEXT_SLOTS)
    token = request.POST.get("font_review", "")
    folder = None
    try:
        if token:
            font_permissions(request, owner, selected)
            folder = read_draft(request, token, selected.code)
            report = json.loads((folder / "report.json").read_text())
            if not report["ready"] or request.POST.get("rendering_reviewed") != "yes":
                raise ValueError(
                    "Check font coverage and review the rendering before creating the language."
                )
            if not report["complete"] and request.POST.get("gaps_reviewed") != "yes":
                raise ValueError(
                    "Review the missing characters or choose another font before creating the language."
                )
        elif needs_fonts:
            raise ValueError("Prepare and review fonts before creating this language.")
        elif not required and request.POST.get("unknown_reviewed") != "yes":
            raise ValueError(
                "Confirm the unknown character coverage before creating this language."
            )
        context_token = creation_draft.set(
            {"component": owner.pk, "language": selected.code, "folder": folder}
            if folder
            else None
        )
        try:
            if owner.translation_set.filter(language=selected).exists():
                raise ValueError(
                    "This language was already created. Open its translation editor."
                )
            # Native creation holds the repository lock and emits the post-add
            # signal only for a newly written catalog.
            response = new_language(request, path=path)
        finally:
            creation_draft.reset(context_token)
        if (
            response.status_code == 302
            and not owner.translation_set.filter(language=selected).exists()
        ):
            from django.contrib.messages import get_messages

            errors = " ".join(str(message) for message in get_messages(request))
            raise ValueError(
                errors
                or "The language could not be created. Review its settings and try again."
            )
        if folder and response.status_code == 302:
            shutil.rmtree(folder, ignore_errors=True)
        return response
    except (ValueError, OSError, RepositoryError) as error:
        return HttpResponse(str(error), status=400, content_type="text/plain")
