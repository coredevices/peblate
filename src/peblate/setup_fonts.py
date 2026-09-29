"""Font preparation shared by setup endpoints and the bounded compiler process."""

import hashlib
import json
from pathlib import Path

import freetype
from pebble_language_tools.extract_builtin_coverage import pbf_codepoints
from pebble_language_tools.generate_codepoint_requirements import uses_emoji_font
from pebble_language_tools.lang_commands import build_font, resolve_font_entries
from pebble_language_tools.language_characters import (
    language_characters,
    with_shaping_forms,
)

from .font_guidance import builtin_coverage

TEXT_SLOTS = tuple(
    name for name in builtin_coverage()["fonts"] if name.startswith("GOTHIC_")
)


def requirements(code):
    locale, characters = language_characters(code)
    return locale, {
        cp
        for cp in with_shaping_forms(characters)
        if chr(cp).isprintable() and not uses_emoji_font(cp)
    }


def checked_path(root, name):
    path = (Path(root) / name).resolve()
    if not path.is_relative_to(Path(root).resolve()):
        raise ValueError("Font assets must stay inside their repository folder.")
    return path


def pack_entries(root, pack, *, resolve=True):
    folder = checked_path(root, pack)
    mapping = json.loads((folder / "lang_map.json").read_text())
    resolved = resolve_font_entries(mapping)
    entries = []
    source_entries = (
        [dict(entry, name=slot) for slot, entry in resolved.items()]
        if resolve
        else mapping["fonts"]
    )
    for original in source_entries:
        entry = dict(original)
        if "alias" in entry:
            entries.append(entry)
            continue
        if not entry.get("file"):
            continue
        if not entry.get("license"):
            licenses = sorted(folder.glob("LICENSE*"))
            if len(licenses) == 1:
                entry["license"] = licenses[0].name
        entries.append(entry)
    return folder, entries


def font_packs(root, code):
    _, required = requirements(code)
    base = builtin_coverage()["fonts"]
    missing = {slot: required - set(base[slot]["codepoints"]) for slot in TEXT_SLOTS}
    total = sum(map(len, missing.values()))
    if not total:
        return []
    result = []
    for path in sorted(Path(root).glob("en_*/lang_map.json")):
        try:
            folder, entries = pack_entries(root, path.parent.name)
            covered = {}
            faces = {}
            licensed = True
            for entry in entries:
                font = checked_path(folder, entry["file"])
                if font not in faces:
                    faces[font] = {
                        cp
                        for cp, glyph in freetype.Face(str(font)).get_chars()
                        if glyph
                    }
                covered[entry["name"]] = faces[font]
                licensed &= bool(
                    entry.get("license")
                    and checked_path(folder, entry["license"]).is_file()
                )
            remaining = sum(
                len(points - covered.get(slot, set()))
                for slot, points in missing.items()
            )
            if remaining < total:
                result.append(
                    {
                        "code": path.parent.name,
                        "complete": remaining == 0,
                        "missing": remaining,
                        "licensed": licensed,
                    }
                )
        except (OSError, ValueError, KeyError, TypeError, freetype.FT_Exception):
            continue
    return sorted(result, key=lambda item: (item["missing"], item["code"]))


def copy_asset(folder, source):
    data = source.read_bytes()
    target = hashlib.sha256(data).hexdigest() + source.suffix
    (folder / target).write_bytes(data)
    return target


def reuse_pack(root, pack, folder):
    source, entries = pack_entries(root, pack, resolve=False)
    for entry in entries:
        if "alias" in entry:
            continue
        if not entry.get("license"):
            raise ValueError(
                "This pack has no identifiable font license. Upload its font and license instead."
            )
        for key in ("file", "license", "characterList"):
            if entry.get(key):
                original = entry[key]
                entry[key] = copy_asset(folder, checked_path(source, original))
                if key in ("file", "license"):
                    entry[
                        "original_name" if key == "file" else "license_original_name"
                    ] = Path(original).name
    return entries


def compile_fonts(folder, code):
    folder = Path(folder)
    _, required = requirements(code)
    codepoints = folder / "requirements.json"
    codepoints.write_text(json.dumps({"codepoints": sorted(required)}))
    entries = json.loads((folder / "fonts.json").read_text())
    results = []
    resolved = resolve_font_entries({"fonts": entries})
    compiled = {}
    for entry in resolved.values():
        if entry["name"] not in compiled:
            compiled[entry["name"]] = (
                build_font(folder, entry, codepoints) if entry.get("file") else b""
            )
    for slot in TEXT_SLOTS:
        data = compiled[resolved[slot]["name"]]
        (folder / (slot + ".pbf")).write_bytes(data)
        missing = required - set(builtin_coverage()["fonts"][slot]["codepoints"])
        missing -= set(pbf_codepoints(data)) if data else set()
        results.append(
            {
                "name": slot,
                "missing": len(missing),
                "examples": "".join(chr(cp) for cp in sorted(missing)[:20]),
            }
        )
    (folder / "report.json").write_text(
        json.dumps(
            {
                "styles": results,
                "ready": True,
                "complete": not any(item["missing"] for item in results),
            }
        )
    )


if __name__ == "__main__":
    import sys

    compile_fonts(sys.argv[1], sys.argv[2])
