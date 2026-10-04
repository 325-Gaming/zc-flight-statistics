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
        app.logged_out = False
        app.relogin_requested = False

        with patch.object(module.threading, "Timer") as timer:
            self.assertIsNone(app.action("main", "close", {}))

        timer.assert_called_once_with(0.2, window.destroy)
        timer.return_value.start.assert_called_once_with()
        window.destroy.assert_not_called()
        self.assertFalse(app.relogin_requested)

    def test_logout_close_returns_to_login_unless_exit_selected(self):
        module = self._load_app_module()
        window = Mock()
        app = module.WebViewApp.__new__(module.WebViewApp)
        app.windows = {"main": window}
        app.logged_out = True
        app.relogin_requested = False
        with patch.object(module.threading, "Timer"):
            app.action("main", "close", {"relogin": True})
            self.assertTrue(app.relogin_requested)
            app.action("main", "close", {"relogin": False})
            self.assertFalse(app.relogin_requested)

    def test_main_reopens_login_only_when_requested(self):
        module = self._load_app_module()
        for relogin in (False, True):
            with self.subTest(relogin=relogin):
                app = Mock(relogin_requested=relogin)
                with patch.object(module, "WebViewApp", return_value=app), \
                     patch.object(module.webview, "start", create=True), \
                     patch.object(module.signal, "signal"), \
                     patch.object(module.os, "execv") as restart:
                    module.main()
                app.finish_close.assert_called_once_with()
                if relogin:
                    restart.assert_called_once_with(module.sys.executable,
                                                    [module.sys.executable, *module.sys.argv])
                else:
                    restart.assert_not_called()

    def test_logout_revokes_session_then_frontend_can_close(self):
        module = self._load_app_module()
        module.core.login_token = object()
        module.core.client = object()
        app = module.WebViewApp.__new__(module.WebViewApp)
        app.logged_out = False
        app.upload_queue = Mock(pending_count=0)
        app._stop_hotkeys = Mock()
        with patch.object(module, "logout", return_value={"message": "退出登录成功"}) as revoke, \
             patch.object(module.threading, "Timer") as timer:
            self.assertEqual(app.action("main", "logout", {}), {"revoked": True})
        revoke.assert_called_once_with(module.core.login_token, client=module.core.client)
        self.assertTrue(app.logged_out)
        app._stop_hotkeys.assert_called_once_with()
        app.upload_queue.close.assert_called_once_with(wait=False)
        timer.assert_not_called()

    def test_logout_failure_keeps_window_open_for_acknowledgement(self):
        module = self._load_app_module()
        module.core.login_token = object()
        module.core.client = object()
        app = module.WebViewApp.__new__(module.WebViewApp)
        app.logged_out = False
        app.upload_queue = Mock(pending_count=0)
        app._stop_hotkeys = Mock()
        with patch.object(module, "logout", side_effect=module.httpx.ConnectError("offline")), \
             patch.object(module.threading, "Timer") as timer:
            self.assertEqual(app.action("main", "logout", {}), {"revoked": False})
        self.assertTrue(app.logged_out)
        timer.assert_not_called()

    def test_logout_error_response_is_not_treated_as_revoked(self):
        module = self._load_app_module()
        module.core.login_token = object()
        module.core.client = object()
        app = module.WebViewApp.__new__(module.WebViewApp)
        app.logged_out = False
        app.upload_queue = Mock(pending_count=0)
        app._stop_hotkeys = Mock()
        with patch.object(module, "logout", return_value={"error": "会话已过期"}):
            self.assertEqual(app.action("main", "logout", {}), {"revoked": False})

    def test_logout_waits_for_queued_uploads(self):
        module = self._load_app_module()
        app = module.WebViewApp.__new__(module.WebViewApp)
        app.logged_out = False
        app.upload_queue = Mock(pending_count=1)
        with patch.object(module, "logout") as revoke:
            with self.assertRaisesRegex(RuntimeError, "上传任务未完成"):
                app.action("main", "logout", {})
        revoke.assert_not_called()


if __name__ == "__main__":
    unittest.main()
