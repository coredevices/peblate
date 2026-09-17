# SPDX-FileCopyrightText: 2026 Core Devices LLC
# SPDX-License-Identifier: Apache-2.0

"""Initial language guidance from the same offline data as the pack tools."""

from functools import lru_cache

from pebble_language_tools.generate_codepoint_requirements import uses_emoji_font
from pebble_language_tools.lang_check import load_builtin_coverage
from pebble_language_tools.language_characters import (
    language_characters,
    with_shaping_forms,
)


@lru_cache(maxsize=1)
def builtin_coverage():
    return load_builtin_coverage()


@lru_cache(maxsize=128)
def baseline_coverage(code):
    locale, characters = language_characters(code)
    if not locale:
        return None
    required = {
        cp
        for cp in with_shaping_forms(characters)
        if chr(cp).isprintable() and not uses_emoji_font(cp)
    }
    return {
        name: len(required - set(font["codepoints"]))
        for name, font in builtin_coverage()["fonts"].items()
    }
