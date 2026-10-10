import json
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

from peblate.asset_store import AssetStore


class AssetStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git(["init", "-b", "main"])
        self.git(["config", "user.name", "Peblate test"])
        self.git(["config", "user.email", "test@localhost"])
        for code in ("he_IL", "de_DE"):
            (self.root / code).mkdir()
            (self.root / code / "tintin.po").write_text(
                'msgid "Music"\nmsgstr "Music"\n'
            )
        self.git(["add", "."])
        self.git(["commit", "-m", "Seed"])
        self.store = AssetStore(self.root, self.git, threading.RLock())

    def git(self, args):
        return subprocess.run(
            ["git", "-C", str(self.root), *args],
            check=True,
            capture_output=True,
            text=True,
        ).stdout

    def upload(self, code="he_IL", slot="GOTHIC_18_EXTENDED"):
        return self.store.upload(
            Path(code) / "tintin.po",
            code,
            slot,
            b"font",
            b"license",
            "example.ttf",
            "LICENSE.txt",
        )

    def test_shared_assets_survive_clone_and_repeat_is_noop(self):
        self.upload()
        self.upload("de_DE")
        self.upload(slot="GOTHIC_24_EXTENDED")
        head = self.git(["rev-parse", "HEAD"])
        self.upload()
        self.assertEqual(head, self.git(["rev-parse", "HEAD"]))
        self.assertEqual(len(list((self.root / "he_IL").glob("*.ttf"))), 1)
        self.assertEqual(len(list((self.root / "de_DE").glob("*.ttf"))), 1)
        self.assertEqual(
            self.git(
                [
                    "rev-parse",
                    "HEAD:he_IL/" + next((self.root / "he_IL").glob("*.ttf")).name,
                ]
            ),
            self.git(
                [
                    "rev-parse",
                    "HEAD:de_DE/" + next((self.root / "de_DE").glob("*.ttf")).name,
                ]
            ),
        )
        self.assertEqual(len(list((self.root / "he_IL").glob("*.license"))), 1)
        with tempfile.TemporaryDirectory() as clone:
            subprocess.run(
                ["git", "clone", "--no-local", str(self.root), clone],
                check=True,
                capture_output=True,
            )
            mapping = json.loads((Path(clone) / "he_IL/lang_map.json").read_text())
            entry = mapping["fonts"][0]
            self.assertEqual(
                (Path(clone) / "he_IL" / entry["file"]).read_bytes(), b"font"
            )
            self.assertEqual(
                (Path(clone) / "he_IL" / entry["license"]).read_bytes(), b"license"
            )

    def test_unrelated_staged_edits_not_committed(self):
        (self.root / "he_IL/tintin.po").write_text("pending translation")
        self.git(["add", "he_IL/tintin.po"])
        self.upload()
        self.assertIn("he_IL/tintin.po", self.git(["diff", "--cached", "--name-only"]))
        self.assertNotIn(
            "he_IL/tintin.po", self.git(["show", "--format=", "--name-only", "HEAD"])
        )

    def replacement(self, slot="GOTHIC_18_EXTENDED"):
        return self.store.upload(
            Path("he_IL/tintin.po"),
            "he_IL",
            slot,
            b"replacement font",
            b"replacement license",
            "replacement.ttf",
            "LICENSE.txt",
        )

    def test_replacement_removes_assets_only_after_last_reference(self):
        original = self.upload()
        self.upload(slot="GOTHIC_24_EXTENDED")
        self.replacement()
        for key in ("file", "license"):
            self.assertTrue((self.root / "he_IL" / original[key]).exists())
        self.replacement("GOTHIC_24_EXTENDED")
        for key in ("file", "license"):
            self.assertFalse((self.root / "he_IL" / original[key]).exists())
            self.assertNotIn("he_IL/" + original[key], self.git(["ls-files"]))
        self.assertEqual(self.git(["status", "--porcelain"]), "")

    def test_replacement_preserves_cross_language_references(self):
        original = self.upload()
        catalog = Path("de_DE/tintin.po")
        mapping = self.store.mapping(catalog, "de_DE")
        mapping["fonts"] = [
            {
                **original,
                "file": "../he_IL/" + original["file"],
                "license": "../he_IL/" + original["license"],
            }
        ]
        self.store.path(catalog.with_name("lang_map.json")).write_bytes(
            self.store.encode(mapping)
        )
        self.git(["add", "."])
        self.git(["commit", "-m", "Share Hebrew font"])
        self.replacement()
        for key in ("file", "license"):
            self.assertTrue((self.root / "he_IL" / original[key]).exists())

    def test_replacement_cleans_old_tracked_orphans_but_preserves_user_files(self):
        self.upload()
        for name in ("obsolete.ttf", "obsolete.license", "notes.txt"):
            (self.root / "he_IL" / name).write_bytes(b"old")
        self.git(["add", "."])
        self.git(["commit", "-m", "Historical uploads"])
        (self.root / "he_IL/local.ttf").write_bytes(b"untracked user font")
        self.replacement()
        for name in ("obsolete.ttf", "obsolete.license"):
            self.assertFalse((self.root / "he_IL" / name).exists())
        for name in ("notes.txt", "local.ttf"):
            self.assertTrue((self.root / "he_IL" / name).exists())

    def test_failed_replacement_restores_deleted_fonts_and_map(self):
        original = self.upload()
        mapping_path = self.root / "he_IL/lang_map.json"
        original_mapping = mapping_path.read_bytes()
        head = self.git(["rev-parse", "HEAD"])

        def fail(args):
            if args[0] == "commit":
                raise RuntimeError("simulated commit failure")
            return self.git(args)

        self.store.git = fail
        with self.assertRaises(RuntimeError):
            self.replacement()
        self.assertEqual(mapping_path.read_bytes(), original_mapping)
        self.assertEqual((self.root / "he_IL" / original["file"]).read_bytes(), b"font")
        self.assertEqual(
            (self.root / "he_IL" / original["license"]).read_bytes(), b"license"
        )
        self.assertEqual(head, self.git(["rev-parse", "HEAD"]))
        self.assertEqual(self.git(["status", "--porcelain"]), "")

    def test_commit_failure_rolls_back_and_retry_works(self):
        original = self.git(["rev-parse", "HEAD"])

        def fail(args):
            if args[0] == "commit":
                raise RuntimeError("simulated commit failure")
            return self.git(args)

        self.store.git = fail
        with self.assertRaises(RuntimeError):
            self.upload()
        self.assertFalse((self.root / "he_IL/lang_map.json").exists())
        self.assertEqual(self.git(["status", "--porcelain"]), "")
        self.assertEqual(original, self.git(["rev-parse", "HEAD"]))
        self.store.git = self.git
        self.upload()

    def test_existing_mapping_restored_on_failure(self):
        self.upload()
        path = self.root / "he_IL/lang_map.json"
        previous = path.read_bytes()

        def fail(args):
            if args[0] == "commit":
                raise RuntimeError("simulated commit failure")
            return self.git(args)

        self.store.git = fail
        with self.assertRaises(RuntimeError):
            self.upload(slot="GOTHIC_24_EXTENDED")
        self.assertEqual(path.read_bytes(), previous)
        self.assertEqual(self.git(["status", "--porcelain"]), "")

    def test_external_resource_is_rejected(self):
        with self.assertRaises(ValueError):
            self.store.resource(Path("he_IL/tintin.po"), "../../outside")

    def test_mapping_only_does_not_create_empty_fonts(self):
        catalog = Path("nb_NO/tintin.po")
        self.store.path(catalog).parent.mkdir()
        self.store.path(catalog).write_text("new catalog")
        # Weblate has just written this file and has not committed it yet.
        mapping = self.store.ensure_mapping(catalog, "nb")
        self.assertEqual(
            mapping["strings"],
            {"lang": "nb_NO", "name": "STRINGS", "file": "tintin.po"},
        )
        self.assertEqual(mapping["fonts"], [])
        self.assertIn("nb_NO/lang_map.json", self.git(["ls-files"]))
        self.assertNotIn("nb_NO/tintin.po", self.git(["ls-files"]))
        self.assertFalse((self.root / "fonts").exists())
        self.git(["add", "--", str(catalog)])
        self.git(["commit", "-m", "Native language creation"])
        self.assertEqual(self.git(["status", "--porcelain"]), "")
        head = self.git(["rev-parse", "HEAD"])
        self.store.ensure_mapping(catalog, "nb")
        self.assertEqual(head, self.git(["rev-parse", "HEAD"]))

    def test_mapping_initialization_preserves_existing_custom_fonts(self):
        self.upload()
        path = self.root / "he_IL/lang_map.json"
        # Imported maps may have different formatting or pending local edits.
        path.write_text(json.dumps(json.loads(path.read_text())))
        original = path.read_bytes()
        head = self.git(["rev-parse", "HEAD"])
        mapping = self.store.ensure_mapping(Path("he_IL/tintin.po"), "he_IL")
        self.assertEqual(
            mapping["fonts"][0]["file"],
            next((self.root / "he_IL").glob("*.ttf")).name,
        )
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(head, self.git(["rev-parse", "HEAD"]))

    def test_prepared_creation_is_one_commit_and_failure_is_clean(self):
        prepared = self.root / "prepared"
        prepared.mkdir()
        (prepared / "font.ttf").write_bytes(b"font")
        (prepared / "license.txt").write_bytes(b"license")
        (prepared / "fonts.json").write_text(
            json.dumps(
                [
                    {
                        "name": "GOTHIC_18_EXTENDED",
                        "file": "font.ttf",
                        "license": "license.txt",
                        "pixelHeight": 14,
                        "extended": True,
                    }
                ]
            )
        )
        catalog = Path("ar_AA/tintin.po")
        self.store.path(catalog).parent.mkdir()
        self.store.path(catalog).write_text("new catalog")
        original = self.git(["rev-parse", "HEAD"])

        def fail(args):
            if args[0] == "commit":
                raise RuntimeError("simulated failure")
            return self.git(args)

        self.store.git = fail
        with self.assertRaises(RuntimeError):
            self.store.install_prepared(catalog, prepared)
        self.assertFalse(self.store.path(catalog).exists())
        self.assertFalse(self.store.path(catalog.with_name("lang_map.json")).exists())
        self.assertEqual(self.git(["rev-parse", "HEAD"]), original)
        self.store.git = self.git
        self.store.path(catalog).write_text("new catalog")
        self.store.install_prepared(catalog, prepared)
        changed = self.git(["show", "--format=", "--name-only", "HEAD"])
        for name in ("tintin.po", "font.ttf", "license.txt", "lang_map.json"):
            self.assertIn("ar_AA/" + name, changed)
        self.assertEqual(
            self.store.mapping(catalog, "ar_AA")["fonts"][0]["pixelHeight"], 14
        )
        with self.assertRaises(ValueError):
            self.store.install_prepared(catalog, prepared)
