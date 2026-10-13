import hashlib
import json
import tempfile
import unittest
from importlib.resources import files
from pathlib import Path
from unittest.mock import patch

from pebble_language_tools.extract_builtin_coverage import pbf_codepoints
from pebble_language_tools.pack_format import FONT_SLOTS

from peblate.font_guidance import baseline_coverage, builtin_coverage
from peblate.font_styles import NUMBER_SLOTS, TEXT_SLOTS, base_font_path
from peblate.setup_fonts import compile_fonts

STATIC = files("peblate") / "static"


class SetupFontTests(unittest.TestCase):
    def test_styles_match_the_pack_slots_in_firmware_order(self):
        self.assertEqual(
            TEXT_SLOTS,
            tuple(name for name in FONT_SLOTS if name.startswith(("GOTHIC_", "LECO_"))),
        )
        self.assertEqual(len(NUMBER_SLOTS), 9)
        for code in ("de", "ru", "he"):
            coverage = baseline_coverage(code)
            for slot in NUMBER_SLOTS:
                self.assertEqual(coverage[slot], 0)

    def test_bundled_number_fonts_match_coverage_and_source_hashes(self):
        snapshot = builtin_coverage()
        for slot in NUMBER_SLOTS:
            with self.subTest(slot=slot):
                data = (STATIC / base_font_path(slot)).read_bytes()
                font = snapshot["fonts"][slot]
                self.assertEqual(set(pbf_codepoints(data)), set(font["codepoints"]))
                self.assertEqual(
                    hashlib.sha256(data).hexdigest(),
                    snapshot["source"]["input_sha256"][font["file"]],
                )

    def test_unassigned_number_styles_are_previewed_without_alphabet_gaps(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "fonts.json").write_text("[]")
            compile_fonts(folder, "ru")
            report = json.loads((folder / "report.json").read_text())
            styles = {item["name"]: item for item in report["styles"]}
            self.assertEqual(set(styles), set(TEXT_SLOTS))
            self.assertTrue(report["ready"])
            self.assertFalse(report["complete"])
            self.assertGreater(styles["GOTHIC_18_EXTENDED"]["missing"], 0)
            for slot in NUMBER_SLOTS:
                self.assertEqual(styles[slot]["missing"], 0)
                self.assertEqual((folder / (slot + ".pbf")).read_bytes(), b"")

    def test_number_font_compile_failures_still_reject_setup(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "fonts.json").write_text(
                json.dumps([{"name": NUMBER_SLOTS[0], "file": "numbers.ttf"}])
            )
            with (
                patch(
                    "peblate.setup_fonts.build_font",
                    side_effect=ValueError("too large"),
                ),
                self.assertRaisesRegex(ValueError, "too large"),
            ):
                compile_fonts(folder, "ru")


if __name__ == "__main__":
    unittest.main()
