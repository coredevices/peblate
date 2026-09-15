# SPDX-FileCopyrightText: 2026 Core Devices LLC
# SPDX-License-Identifier: Apache-2.0

from django import template
from django.templatetags.static import static
from django.urls import reverse

from peblate.permissions import capabilities
from peblate.views import SLOTS, font_assignment, mapping_for
from peblate.weblate_adapter import enabled_component

register = template.Library()


@register.inclusion_tag("pebble/editor_panel.html", takes_context=True)
def pebble_editor_panel(context, unit):
    request = context["request"]
    if (
        not unit
        or not capabilities(request.user, unit.translation)["preview"]
        or unit.translation.component.full_slug != enabled_component()
    ):
        return {"enabled": False}
    code = unit.translation.language_code
    mapping = {
        entry["name"]: entry
        for entry in mapping_for(code)["fonts"]
        if entry.get("file")
    }
    slots = [
        {
            **font_assignment(code, mapping.get(name)),
            "name": name,
            "extension_url": reverse("pebble-font-pbf", args=[code, name]),
            "label": label,
            "pbf_url": static(
                "pebble/renderer/" + name.removesuffix("_EXTENDED") + ".pbf"
            ),
            "font_url": reverse("pebble-font", args=[code, name])
            if name in mapping
            else None,
        }
        for name, label in SLOTS
    ]
    return {
        "enabled": True,
        "permissions": capabilities(request.user, unit.translation),
        "code": code,
        "slots": slots,
        "request": request,
        "csrf_token": context["csrf_token"],
        "language_name": unit.translation.language.name,
    }
