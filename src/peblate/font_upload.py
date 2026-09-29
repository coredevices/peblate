"""Validate uploaded fonts and their redistribution licenses."""

import tempfile
from pathlib import Path

import freetype


def validate_upload(uploaded, license_file, *, license_data=None):
    if not uploaded or not 0 < uploaded.size <= 20 * 1024 * 1024:
        raise ValueError("Choose a font smaller than 20 MB.")
    content = uploaded.read()
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "font.ttf"
        path.write_bytes(content)
        try:
            face = freetype.Face(str(path))
            face.set_pixel_sizes(0, 18)
        except freetype.FT_Exception:
            raise ValueError(
                "This file could not be read as a font. Upload a TTF or OTF font."
            ) from None
    if license_data is None:
        if not license_file or not 0 < license_file.size <= 1024 * 1024:
            raise ValueError("Upload the font license as text or PDF (up to 1 MB).")
        license_data = license_file.read()
    if not license_data.startswith(b"%PDF-"):
        try:
            if not license_data.decode("utf-8").strip() or b"\0" in license_data:
                raise ValueError
        except (UnicodeDecodeError, ValueError):
            raise ValueError(
                "The license must be a non-empty UTF-8 text file or PDF."
            ) from None
    return (
        content,
        license_data,
        uploaded.name,
        license_file.name if license_file else "license.txt",
    )
