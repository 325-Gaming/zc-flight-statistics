"""Check policy enforcement for data-entry Release builds."""

import importlib.util
import pathlib
import unittest


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


if __name__ == "__main__":
    unittest.main()
