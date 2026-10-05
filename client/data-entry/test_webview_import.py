"""Check the passenger import window's file and confirmation behavior."""

import importlib.util
import pathlib
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch


class WebViewImportTests(unittest.TestCase):
    @staticmethod
    def _load_app_module():
        fake_core = types.ModuleType("main")
        fake_core._name = "Zc 测试"
        fake_core._version = "V0"
        fake_core.BASE_DIR = pathlib.Path(__file__).parent
        fake_webview = types.ModuleType("webview")
        fake_webview.FileDialog = types.SimpleNamespace(OPEN="open")
        module_path = pathlib.Path(__file__).with_name("webview_app.py")
        spec = importlib.util.spec_from_file_location("webview_app_import_test", module_path)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"main": fake_core, "webview": fake_webview}):
            spec.loader.exec_module(module)
        return module

    def test_file_selection_only_returns_text_until_confirmed(self):
        module = self._load_app_module()
        app = module.WebViewApp.__new__(module.WebViewApp)
        app.logged_out = False
        app.user_name_list = ["原乘客"]
        app._current_user = Mock()
        file_window = Mock()
        app.windows = {"import": file_window}

        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "name.csv"
            path.write_text("\ufeff甲\n乙\n", encoding="utf-8")
            file_window.create_file_dialog.return_value = (str(path),)
            self.assertEqual(app.action("import", "open_file", {}), "甲\n乙\n")
            self.assertEqual(app.user_name_list, ["原乘客"])
            file_window.create_file_dialog.return_value = None
            self.assertIsNone(app.action("import", "open_file", {}))

        self.assertTrue(app.action("import", "confirm", {"text": " 甲 \n\n乙\r\n"}))
        self.assertEqual(app.user_name_list, ["甲", "乙"])
        app._current_user.assert_called_once_with(0)

    def test_empty_text_keeps_existing_passengers(self):
        module = self._load_app_module()
        app = module.WebViewApp.__new__(module.WebViewApp)
        app.logged_out = False
        app.user_name_list = ["原乘客"]
        app._current_user = Mock()

        with self.assertRaisesRegex(ValueError, "没有乘客姓名"):
            app.action("import", "confirm", {"text": " \n\t"})

        self.assertEqual(app.user_name_list, ["原乘客"])
        app._current_user.assert_not_called()


if __name__ == "__main__":
    unittest.main()
