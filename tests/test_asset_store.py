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
        self.store.ensure_mapping(Path("he_IL/tintin.po"), "he_IL")
        self.assertFalse((self.root / "fonts").exists())
        self.assertEqual(self.git(["status", "--porcelain"]), "")
