"""Repository-backed font assets, independent of Django and Weblate."""

import hashlib
import json
import os
from pathlib import Path


class AssetStore:
    def __init__(self, root, git, lock):
        self.root = Path(root).resolve()
        self.git = git
        self.lock = lock

    def path(self, relative):
        path = self.root / relative
        if not path.resolve().is_relative_to(self.root):
            raise ValueError("Asset path must stay inside the translation repository.")
        return path

    def mapping(self, catalog, code):
        path = self.path(Path(catalog).with_name("lang_map.json"))
        if path.exists():
            return json.loads(path.read_text())
        return {
            "strings": {
                "lang": Path(catalog).parent.name,
                "name": "STRINGS",
                "file": Path(catalog).name,
            },
            "fonts": [],
            "images": [],
        }

    def resource(self, catalog, name):
        return self.path(Path(catalog).parent / name)

    def _commit(self, contents, message):
        # Caller holds Weblate's repository lock across read, write, and commit.
        changed = {
            name: data
            for name, data in contents.items()
            if not self.path(name).exists() or self.path(name).read_bytes() != data
        }
        if not changed:
            return False
        names = sorted(changed)
        if self.git(["status", "--porcelain", "--", *names]).strip():
            raise ValueError(
                "These font files have uncommitted changes. Resolve them before uploading again."
            )
        previous = {
            name: self.path(name).read_bytes() if self.path(name).exists() else None
            for name in names
        }
        try:
            for name, data in changed.items():
                path = self.path(name)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            self.git(["add", "--", *names])
            # --only keeps unrelated staged translations out of this asset commit.
            self.git(["commit", "--only", "-m", message, "--", *names])
        except Exception:
            self.git(["reset", "--", *names])
            for name, data in previous.items():
                path = self.path(name)
                if data is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_bytes(data)
            raise
        return True

    def ensure_mapping(self, catalog, code):
        with self.lock:
            mapping = self.mapping(catalog, code)
            self._commit(
                {str(Path(catalog).with_name("lang_map.json")): self.encode(mapping)},
                f"Initialize {code} language-pack resources",
            )
            return mapping

    @staticmethod
    def encode(mapping):
        return (json.dumps(mapping, ensure_ascii=False, indent=2) + "\n").encode()

    def upload(self, catalog, code, slot, font, license_data, font_name, license_name):
        with self.lock:
            font_path = str(
                Path(catalog).parent / (hashlib.sha256(font).hexdigest() + ".ttf")
            )
            license_path = str(
                Path(catalog).parent
                / (hashlib.sha256(license_data).hexdigest() + ".license")
            )
            folder = self.path(Path(catalog).parent)
            entry = {
                "name": slot,
                "file": os.path.relpath(self.path(font_path), folder),
                "license": os.path.relpath(self.path(license_path), folder),
                "extended": True,
                "original_name": Path(font_name).name,
                "license_original_name": Path(license_name).name,
            }
            mapping = self.mapping(catalog, code)
            mapping["fonts"] = sorted(
                [item for item in mapping["fonts"] if item["name"] != slot] + [entry],
                key=lambda item: item["name"],
            )
            self._commit(
                {
                    font_path: font,
                    license_path: license_data,
                    str(Path(catalog).with_name("lang_map.json")): self.encode(mapping),
                },
                f"Update {code} font for {slot}",
            )
            return entry

    def snapshot(self, catalog, code, folder):
        """Copy a consistent build input under the repository lock; caches stay elsewhere."""
        with self.lock:
            mapping = self.mapping(catalog, code)
            folder.mkdir(parents=True)
            (folder / "tintin.po").write_bytes(self.path(catalog).read_bytes())
            mapping["strings"]["file"] = "tintin.po"
            for entry in mapping["fonts"]:
                if not entry.get("file"):
                    continue
                if (
                    not entry.get("license")
                    or not self.resource(catalog, entry["license"]).is_file()
                ):
                    raise ValueError(
                        "Upload each custom font with its license before building a pack."
                    )
                for key in ("file", "license", "characterList"):
                    if entry.get(key):
                        source = self.resource(catalog, entry[key])
                        # Keep distinct filenames even for arbitrary imported resource maps.
                        name = (
                            hashlib.sha256(source.read_bytes()).hexdigest()
                            + source.suffix
                        )
                        (folder / name).write_bytes(source.read_bytes())
                        entry[key] = name
            (folder / "lang_map.json").write_bytes(self.encode(mapping))
