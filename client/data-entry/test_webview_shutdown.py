"""Keep GUI close callbacks independent of upload queue completion."""

import importlib.util
import pathlib
import sys
import threading
import types
import unittest
from unittest.mock import Mock, patch


class WebViewShutdownTests(unittest.TestCase):
    @staticmethod
    def _load_app_module():
        fake_core = types.ModuleType("main")
        fake_core._name = "Zc 测试"
        fake_core._version = "V0"
        fake_core._version_number = "0.0.0"
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

    def test_update_checks_then_closes_main_only_after_helper_starts(self):
        module = self._load_app_module()
        app = module.WebViewApp.__new__(module.WebViewApp)
        app.logged_out = False
        app.update_offer = None
        app.update_policy = {"minimum_supported_version": "2.2.0"}
        app.upload_queue = Mock(pending_count=0)
        app.predict_lock = module.threading.Lock()
        app.windows = {"main": Mock()}
        offer = {"available": True, "mode": "release", "version": "2.2.0",
                 "current_version": "2.1.0", "url": "private backend value"}
        with patch.object(module, "check_update", return_value=offer), \
             patch.object(module, "start_update") as start, \
             patch.object(module.threading, "Timer") as timer:
            self.assertEqual(app.action("update", "check", {}),
                             {"available": True, "mode": "release", "version": "2.2.0",
                              "current_version": "2.1.0"})
            self.assertEqual(app.action("update", "install", {}), {"restarting": True})
        start.assert_called_once()
        timer.assert_called_once_with(0.3, app.windows["main"].destroy)
        timer.return_value.start.assert_called_once_with()
        self.assertIsNone(app.update_offer)

    def test_update_refuses_pending_upload_without_closing(self):
        module = self._load_app_module()
        app = module.WebViewApp.__new__(module.WebViewApp)
        app.logged_out = False
        app.update_offer = {"available": True}
        app.update_policy = {"minimum_supported_version": "2.2.0"}
        app.upload_queue = Mock(pending_count=1)
        app.predict_lock = module.threading.Lock()
        with patch.object(module, "start_update") as start:
            with self.assertRaisesRegex(RuntimeError, "上传或识别任务"):
                app.action("update", "install", {})
        start.assert_not_called()

    def test_business_actions_and_hotkeys_are_locked_before_startup_check(self):
        module = self._load_app_module()
        app = module.WebViewApp.__new__(module.WebViewApp)
        app.startup_complete = False
        app.update_policy = None
        app.settings_open = False
        app.closed = False
        with self.assertRaisesRegex(RuntimeError, "启动联网检查尚未通过"):
            app.action("main", "select", {"index": 0})
        app._register_hotkeys = Mock()
        app.start_hotkeys()
        app._register_hotkeys.assert_not_called()

    def test_required_gate_cannot_continue_or_start_update_without_explicit_install(self):
        module = self._load_app_module()
        app = module.WebViewApp.__new__(module.WebViewApp)
        app.startup_complete = False
        app.closed = False
        app.gate_lock = threading.RLock()
        app.gate_state = {"phase": "required"}
        app.update_offer = {"available": True, "version": "2.2.0"}
        with self.assertRaisesRegex(ValueError, "尚未允许进入"):
            app.action("gate", "continue", {})
        with patch.object(module.threading, "Thread") as thread:
            self.assertEqual(app.action("gate", "install", {}), {"started": True})
        thread.assert_called_once()
        self.assertEqual(app.gate_state["phase"], "installing-required")

    def test_gate_retry_deduplicates_an_active_startup_check(self):
        module = self._load_app_module()
        app = module.WebViewApp.__new__(module.WebViewApp)
        app.closed = False
        app.startup_active = True
        app.gate_lock = threading.RLock()
        app.gate_state = {"phase": "error", "message": "offline"}
        with patch.object(module.threading, "Thread") as thread:
            self.assertEqual(app.action("gate", "retry", {}), {"started": True})
        thread.assert_not_called()
        self.assertEqual(app.gate_state["phase"], "error")

    def test_startup_policy_failure_stays_in_retry_or_exit_gate(self):
        module = self._load_app_module()
        app = module.WebViewApp.__new__(module.WebViewApp)
        app.closed = False
        app.gate_lock = threading.RLock()
        app.startup_active = True
        app.gate_state = {"phase": "checking"}
        with patch.object(module, "recover_incomplete_update"), \
             patch.object(module, "fetch_update_policy", side_effect=ValueError("HTTP 503")), \
             patch.object(module, "read_update_failure") as read_failure, \
             patch.object(module, "check_startup_update") as check:
            app._run_startup_check()
        read_failure.assert_not_called()
        check.assert_not_called()
        self.assertEqual(app.gate_state["phase"], "error")
        self.assertIn("HTTP 503", app.gate_state["message"])
        self.assertFalse(app.startup_active)

    def test_startup_required_result_waits_for_user_to_install(self):
        module = self._load_app_module()
        app = module.WebViewApp.__new__(module.WebViewApp)
        app.closed = False
        app.gate_lock = threading.RLock()
        app.startup_active = True
        app.gate_state = {"phase": "checking"}
        offer = {"available": True, "version": "2.3.0"}
        with patch.object(module, "recover_incomplete_update"), \
             patch.object(module, "fetch_update_policy", return_value={
                 "minimum_supported_version": "2.2.0",
                 "message": "需更新",
             }), \
             patch.object(module, "read_update_failure", return_value=None), \
             patch.object(module, "check_startup_update", return_value={
                 "required": True, "offer": offer,
             }), \
             patch.object(module, "start_update") as install:
            app._run_startup_check()
        self.assertEqual(app.gate_state["phase"], "required")
        self.assertEqual(app.update_offer, offer)
        install.assert_not_called()

    def test_explicit_gate_install_prepares_update_and_only_then_hands_off(self):
        module = self._load_app_module()
        app = module.WebViewApp.__new__(module.WebViewApp)
        app.closed = False
        app.gate_lock = threading.RLock()
        app.gate_state = {"phase": "installing-required"}
        app.update_offer = {"version": "2.3.0"}
        app.update_policy = {"minimum_supported_version": "2.2.0"}
        with patch.object(module, "start_update") as install, \
             patch.object(module, "os") as os_module:
            os_module.getpid.return_value = 321
            app._prepare_gate_update()
        install.assert_called_once()
        self.assertEqual(app.gate_state["phase"], "restarting")

    def test_background_result_never_touches_a_closed_gate(self):
        module = self._load_app_module()
        app = module.WebViewApp.__new__(module.WebViewApp)
        app.closed = True
        app.gate_lock = threading.RLock()
        app.startup_active = True
        app.gate_state = {"phase": "error", "message": "closed"}
        with patch.object(module, "recover_incomplete_update"), \
             patch.object(module, "fetch_update_policy", return_value={
                 "minimum_supported_version": "2.2.0",
             }), \
             patch.object(module, "read_update_failure", return_value=None), \
             patch.object(module, "check_startup_update", return_value={
                 "required": False, "offer": {"available": False},
             }):
            app._run_startup_check()
        self.assertEqual(app.gate_state, {"phase": "error", "message": "closed"})
        self.assertFalse(app.startup_active)

    def test_closing_gate_after_successful_entry_keeps_main_window_open(self):
        module = self._load_app_module()
        gate = Mock()
        app = module.WebViewApp.__new__(module.WebViewApp)
        app.windows = {"gate": gate, "main": Mock()}
        app.closed = False
        app.startup_complete = True
        app.close = Mock()
        app._window_closed("gate", gate)
        app.close.assert_not_called()
        self.assertIn("main", app.windows)


if __name__ == "__main__":
    unittest.main()
