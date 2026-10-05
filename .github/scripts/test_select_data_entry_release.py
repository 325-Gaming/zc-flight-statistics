"""Check scheduled data-entry tag selection without contacting GitHub."""

import contextlib
import importlib.util
import io
import pathlib
import unittest
from unittest.mock import patch


SCRIPT = pathlib.Path(__file__).with_name("select_data_entry_release.py")
SPEC = importlib.util.spec_from_file_location("select_data_entry_release", SCRIPT)
selector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(selector)


class SelectDataEntryReleaseTests(unittest.TestCase):
    def test_selects_newest_unpublished_semantic_version(self):
        tags = ["data-entry/v0.3.25", "data-entry/v2.1.0", "data-entry/v2.1.1",
                "data-entry/v2.2.0", "data-entry/v2.10.0", "other/v99.0.0"]
        self.assertEqual(selector.select_tag(tags, ["data-entry/v2.1.0"]),
                         "data-entry/v2.10.0")

    def test_does_not_publish_old_unreleased_tag_after_newer_release(self):
        tags = ["data-entry/v0.3.25", "data-entry/v2.1.0", "data-entry/v2.1.1"]
        self.assertIsNone(selector.select_tag(tags, ["data-entry/v2.1.1"]))

    def test_existing_release_or_draft_is_not_selected_again(self):
        tags = ["data-entry/v2.1.0", "data-entry/v2.1.1"]
        self.assertIsNone(selector.select_tag(tags, ["data-entry/v2.1.1"]))

    def test_main_prints_output_only_when_a_tag_is_pending(self):
        remote = ("hash\trefs/tags/data-entry/v2.1.0\n"
                  "hash\trefs/tags/data-entry/v2.1.1\n")
        with patch.dict(selector.os.environ, {"GITHUB_REPOSITORY": "owner/repo"}), \
             patch.object(selector, "run", side_effect=[remote, "data-entry/v2.1.0\n"]), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            selector.main()
        self.assertEqual(output.getvalue(), "tag=data-entry/v2.1.1\n")


if __name__ == "__main__":
    unittest.main()
