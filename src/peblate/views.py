# SPDX-FileCopyrightText: 2026 Core Devices LLC
# SPDX-License-Identifier: Apache-2.0

"""Pebble language assets and previews; Weblate owns translation editing."""

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

import freetype
from django.conf import settings
from django.contrib import messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_POST
from weblate.vcs.base import RepositoryError

from .permissions import require_capability
from .weblate_adapter import (
    component,
    language_store,
    translation_for_code,
)

CACHE_ROOT = Path(settings.PEBLATE_CACHE_ROOT)
SLOTS = (
    ("GOTHIC_14_EXTENDED", "Small text · 14 px"),
    ("GOTHIC_14_BOLD_EXTENDED", "Small bold text · 14 px"),
    ("GOTHIC_18_EXTENDED", "Body text · 18 px"),
    ("GOTHIC_18_BOLD_EXTENDED", "Body bold text · 18 px"),
    ("GOTHIC_24_EXTENDED", "Large text · 24 px"),
    ("GOTHIC_24_BOLD_EXTENDED", "Large bold text · 24 px"),
    ("GOTHIC_28_EXTENDED", "Heading · 28 px"),
    ("GOTHIC_28_BOLD_EXTENDED", "Bold heading · 28 px"),
    ("GOTHIC_36_EXTENDED", "Large heading · 36 px"),
    ("GOTHIC_36_BOLD_EXTENDED", "Large bold heading · 36 px"),
)


def translation_for(code):
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_@.-]*", code):
        raise Http404
    return translation_for_code(code)


def mapping_for(code):
    store, catalog = language_store(code)
    with store.lock:
        return store.mapping(catalog, code)


def asset_path(code, entry, key="file"):
    store, catalog = language_store(code)
    return store.resource(catalog, entry[key])


def font_assignment(code, entry):
    if not entry or not entry.get("file"):
        return {"font_name": None, "license_name": None, "reuse_key": None}
    name = entry.get("original_name")
    if not name:
        try:
            face = freetype.Face(str(asset_path(code, entry)))
            name = " ".join(
                part.decode("utf-8", errors="replace")
                for part in (face.family_name, face.style_name)
                if part
            )
        except (freetype.FT_Exception, OSError):
            name = "Uploaded font"
    return {
        "reuse_key": hashlib.sha256(
            json.dumps([entry["file"], entry.get("license")]).encode()
        ).hexdigest(),
        "font_name": name,
        "license_name": entry.get("license_original_name", "Uploaded license")
        if entry.get("license")
        else None,
    }


@require_capability()
def home(request):
    return redirect(component().get_absolute_url())


@require_capability("preview")
def language(request, code):
    return redirect(translation_for(code).get_translate_url())


@require_capability("upload")
@require_POST
def upload_font(request, code):
    translation_for(code)
    slot = request.POST.get("slot")
    if slot not in dict(SLOTS):
        return HttpResponse("Choose a text style.", status=400)
    uploaded = request.FILES.get("font")
    license_file = request.FILES.get("license")
    reuse = request.POST.get("reuse_slot")
    if reuse:
        if reuse not in dict(SLOTS):
            return HttpResponse(
                "Choose an existing text style.", status=400, content_type="text/plain"
            )
        try:
            store, catalog = language_store(code)
            with store.lock:
                entry = next(
                    (
                        item
                        for item in store.mapping(catalog, code)["fonts"]
                        if item["name"] == reuse
                    ),
                    None,
                )
                if not entry or not entry.get("file") or not entry.get("license"):
                    raise ValueError("Choose a font that already has a license.")
                uploaded = SimpleUploadedFile(
                    entry.get("original_name", "font.ttf"),
                    store.resource(catalog, entry["file"]).read_bytes(),
                )
                license_file = SimpleUploadedFile(
                    entry.get("license_original_name", "license.txt"),
                    store.resource(catalog, entry["license"]).read_bytes(),
                )
        except (ValueError, OSError) as error:
            return HttpResponse(str(error), status=400, content_type="text/plain")
    if not uploaded or uploaded.size > 20 * 1024 * 1024:
        return HttpResponse("Choose a font smaller than 20 MB.", status=400)
    content = uploaded.read()
    with tempfile.TemporaryDirectory() as temp:
        test = Path(temp) / "font.ttf"
        test.write_bytes(content)
        try:
            face = freetype.Face(str(test))
            face.set_pixel_sizes(0, 18)
        except freetype.FT_Exception:
            return HttpResponse(
                "This file could not be read as a font. Upload a TTF or OTF font.",
                status=400,
            )
    if not license_file or not 0 < license_file.size <= 1024 * 1024:
        return HttpResponse(
            "Upload the font license as text or PDF (up to 1 MB).",
            status=400,
            content_type="text/plain",
        )
    license_content = license_file.read()
    if not license_content.startswith(b"%PDF-"):
        try:
            if not license_content.decode("utf-8").strip() or b"\0" in license_content:
                raise ValueError
        except (UnicodeDecodeError, ValueError):
            return HttpResponse(
                "The license must be a non-empty UTF-8 text file or PDF.",
                status=400,
                content_type="text/plain",
            )
    try:
        store, catalog = language_store(code)
        entry = store.upload(
            catalog,
            code,
            slot,
            content,
            license_content,
            uploaded.name,
            license_file.name,
        )
    except (ValueError, OSError, RepositoryError) as error:
        return HttpResponse(
            f"Font could not be saved: {error}", status=400, content_type="text/plain"
        )
    if request.POST.get("format") == "json":
        return JsonResponse(
            {
                **font_assignment(code, entry),
                "slot": slot,
                "font_url": reverse("pebble-font", args=[code, slot])
                + "?v="
                + hashlib.sha256(content).hexdigest()[:12],
            }
        )
    messages.success(
        request, "Font saved. Run validation to check its coverage and size."
    )
    return redirect("pebble-language", code=code)


@require_capability("preview")
def font_file(request, code, slot):
    translation_for(code)
    entry = next(
        (entry for entry in mapping_for(code)["fonts"] if entry["name"] == slot), None
    )
    if not entry or not entry.get("file"):
        raise Http404
    return FileResponse((asset_path(code, entry)).open("rb"), content_type="font/ttf")


@require_capability("preview")
@require_POST
def preview_font(request, code, slot):
    translation_for(code)
    entry = next(
        (item for item in mapping_for(code)["fonts"] if item["name"] == slot), None
    )
    if not entry or not entry.get("file") or slot not in dict(SLOTS):
        raise Http404
    if not entry.get("license") or not (asset_path(code, entry, "license")).is_file():
        return HttpResponse(
            "Upload this font again with its license to enable preview and pack building.",
            status=400,
            content_type="text/plain",
        )
    text = request.POST.get("text", "")
    if len(text.encode("utf-8")) > 8192:
        return HttpResponse(
            "Preview text is limited to 8 KB.", status=400, content_type="text/plain"
        )
    # Use the same subsetting and compatibility limits as pack building.
    import polib
    from pebble_language_tools.generate_codepoint_requirements import (
        generate_codepoint_requirements,
    )
    from pebble_language_tools.lang_commands import build_font

    try:
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            catalog = polib.POFile()
            catalog.append(polib.POEntry(msgid="preview", msgstr=text))
            po = temp / "preview.po"
            catalog.save(str(po))
            store, catalog_path = language_store(code)
            requirements = generate_codepoint_requirements(
                po, language=catalog_path.parent.name
            )
            key = hashlib.sha256(
                json.dumps([entry, requirements], sort_keys=True).encode()
            ).hexdigest()
            cache = CACHE_ROOT / "compiled"
            cache.mkdir(parents=True, exist_ok=True)
            result = cache / (key + ".pbf")
            if not result.exists():
                codepoints = temp / "codepoints.json"
                codepoints.write_text(json.dumps(requirements))
                store, catalog_path = language_store(code)
                with store.lock:
                    data = build_font(
                        store.path(catalog_path.parent), entry, codepoints
                    )
                with tempfile.NamedTemporaryFile(dir=cache, delete=False) as staged:
                    staged.write(data)
                os.replace(staged.name, result)
            return HttpResponse(
                result.read_bytes(), content_type="application/octet-stream"
            )
    except (ValueError, OSError, RuntimeError) as error:
        return HttpResponse(str(error), status=400, content_type="text/plain")


@require_capability()
def setup_coverage(request):
    from django.core.exceptions import PermissionDenied
    from django.shortcuts import get_object_or_404
    from weblate.lang.models import Language

    from .font_guidance import baseline_coverage

    owner = component()
    if not request.user.has_perm(
        "translation.add", owner
    ) or not owner.can_add_new_language(request.user):
        raise PermissionDenied
    selected = get_object_or_404(Language, code=request.GET.get("language", ""))
    coverage = baseline_coverage(selected.code)
    return JsonResponse(
        {
            "language": selected.name,
            "known": coverage is not None,
            "styles": [
                {"label": label, "missing": coverage[name]}
                for name, label in SLOTS
                if coverage and coverage[name]
            ],
        }
    )
