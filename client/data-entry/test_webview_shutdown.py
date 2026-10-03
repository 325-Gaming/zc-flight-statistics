"""Keep GUI close callbacks independent of upload queue completion."""

import importlib.util
import pathlib
import sys
import types
import unittest
from unittest.mock import Mock, patch


class WebViewShutdownTests(unittest.TestCase):
    @staticmethod
    def _load_app_module():
        fake_core = types.ModuleType("main")
        fake_core._name = "Zc 测试"
        fake_core._version = "V0"
        fake_core.BASE_DIR = pathlib.Path(__file__).parent
        fake_webview = types.ModuleType("webview")
        module_path = pathlib.Path(__file__).with_name("webview_app.py")
        spec = importlib.util.spec_from_file_location("webview_app_shutdown_test", module_path)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"main": fake_core, "webview": fake_webview}):
            spec.loader.exec_module(module)
        return module

    def test_main_window_close_never_waits_for_upload_worker(self):
        module = self._load_app_module()

        main_window = Mock()
        history_window = Mock()
        queue = Mock()
        app = module.WebViewApp.__new__(module.WebViewApp)
        app.closed = False
        app.windows = {"main": main_window, "history": history_window}
        app.upload_queue = queue

        app._window_closed("main", main_window)

        self.assertTrue(app.closed)
        queue.close.assert_called_once_with(wait=False)
        history_window.destroy.assert_called_once_with()
        main_window.destroy.assert_not_called()

    def test_page_close_returns_before_destroying_window(self):
        module = self._load_app_module()
        window = Mock()
        app = module.WebViewApp.__new__(module.WebViewApp)
        app.windows = {"main": window}

        with patch.object(module.threading, "Timer") as timer:
            self.assertIsNone(app.action("main", "close", {}))

        timer.assert_called_once_with(0.2, window.destroy)
        timer.return_value.start.assert_called_once_with()
        window.destroy.assert_not_called()


if __name__ == "__main__":
    unittest.main()
