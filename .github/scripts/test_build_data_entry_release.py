"""Check policy enforcement for data-entry Release builds."""

import importlib.util
import json
import pathlib
import tempfile
import unittest
import zipfile
from unittest.mock import patch


SCRIPT = pathlib.Path(__file__).with_name("build_data_entry_release.py")
SPEC = importlib.util.spec_from_file_location("build_data_entry_release", SCRIPT)
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


class BuildDataEntryReleaseTests(unittest.TestCase):
    def test_release_tag_must_be_valid_and_meet_policy_floor(self):
        self.assertEqual(
            builder.validate_release_version("data-entry/v2.2.0", "2.2.0"),
            "2.2.0",
        )
        self.assertEqual(
            builder.validate_release_version("data-entry/v2.10.0", "2.2.0"),
            "2.10.0",
        )
        for tag in ("data-entry/v2.1.9", "v2.2.0", "data-entry/v2.2"):
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                builder.validate_release_version(tag, "2.2.0")

    def test_release_zip_contains_local_gate_styles_and_fonts(self):
        root = builder.REPOSITORY_ROOT
        asset_paths = sorted(builder.REQUIRED_WEBVIEW_ASSETS)
        files = {
            "version.py": b'__version__ = "2.3.0"\n',
            **{
                name: (root / "client/data-entry" / name).read_bytes()
                for name in asset_paths
            },
        }
        object_ids = {
            name: f"{index:040x}" for index, name in enumerate(files, start=1)
        }
        records = [
            f"100644 blob {object_ids[name]}\tclient/data-entry/{name}".encode("utf-8")
            for name in files
        ]
        tree = b"\0".join(records) + b"\0"

        def fake_git(*arguments):
            if arguments[0] == "ls-tree":
                return tree
            if arguments[0] == "rev-parse":
                return b"a" * 40
            if arguments[:2] == ("cat-file", "blob"):
                return files[next(name for name, oid in object_ids.items()
                                  if oid == arguments[2])]
            raise AssertionError(f"Unexpected git command: {arguments}")

        with tempfile.TemporaryDirectory() as directory:
            archive_path = pathlib.Path(directory) / "data-entry-v2.3.0.zip"
            with patch.object(builder, "git", side_effect=fake_git):
                builder.build("data-entry/v2.3.0", archive_path)
            with zipfile.ZipFile(archive_path) as archive:
                packaged = set(archive.namelist())
                manifest = json.loads(archive.read("release-manifest.json"))

        self.assertTrue(builder.REQUIRED_WEBVIEW_ASSETS <= packaged)
        self.assertTrue(builder.REQUIRED_WEBVIEW_ASSETS <= manifest["files"].keys())


if __name__ == "__main__":
    unittest.main()
