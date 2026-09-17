# SPDX-FileCopyrightText: 2026 Core Devices LLC
# SPDX-License-Identifier: Apache-2.0

import re
import unittest

from peblate.language_policy import TRANSLATION_LANGUAGE_FILTER


class LanguagePolicyTest(unittest.TestCase):
    def test_english_and_font_only_variants_are_not_translation_targets(self):
        for code in (
            "en",
            "en_US",
            "en_IL",
            "en_SA",
            "en_TW",
            "en-CN",
            "EN_MY",
            "en@variant",
        ):
            with self.subTest(code=code):
                self.assertIsNone(re.match(TRANSLATION_LANGUAGE_FILTER, code))

    def test_real_translation_targets_remain_available(self):
        for code in ("he_IL", "ar_SA", "zh_TW", "de", "de_DE", "ja_JP", "fr_CA"):
            with self.subTest(code=code):
                self.assertIsNotNone(re.match(TRANSLATION_LANGUAGE_FILTER, code))
