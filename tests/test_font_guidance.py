import unittest

from peblate.font_guidance import baseline_coverage


class FontGuidanceTests(unittest.TestCase):
    def test_specialized_fonts_do_not_require_the_german_alphabet(self):
        coverage = baseline_coverage("de")
        self.assertEqual(coverage["GOTHIC_18_EXTENDED"], 0)
        self.assertEqual(coverage["BITHAM_18_LIGHT_SUBSET_EXTENDED"], 0)
        self.assertEqual(coverage["BITHAM_34_LIGHT_SUBSET_EXTENDED"], 0)
        self.assertEqual(coverage["BITHAM_34_MEDIUM_NUMBERS_EXTENDED"], 0)
        self.assertEqual(coverage["BITHAM_42_MEDIUM_NUMBERS_EXTENDED"], 0)
        self.assertEqual(coverage["ROBOTO_BOLD_SUBSET_49_EXTENDED"], 0)

    def test_general_text_font_gaps_remain_visible(self):
        coverage = baseline_coverage("he")
        self.assertGreater(coverage["GOTHIC_18_EXTENDED"], 0)
        self.assertGreater(coverage["BITHAM_30_BLACK_EXTENDED"], 0)
        self.assertEqual(coverage["BITHAM_42_MEDIUM_NUMBERS_EXTENDED"], 0)


if __name__ == "__main__":
    unittest.main()
