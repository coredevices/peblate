# SPDX-FileCopyrightText: 2026 Core Devices LLC
# SPDX-License-Identifier: Apache-2.0

import re

# English is firmware source; en_* catalogs only supply additional font coverage.
TRANSLATION_LANGUAGE_FILTER = r"^(?!(?i:en)(?:[_@-]|$))[^.]+$"


def translation_language_allowed(code):
    return bool(re.match(TRANSLATION_LANGUAGE_FILTER, code))
