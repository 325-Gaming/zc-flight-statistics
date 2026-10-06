"""Test startup-gate recovery and its offline visual assets."""

import contextlib
import io
import importlib.util
import pathlib
import re
import sys
import types
import unittest
from unittest.mock import Mock, patch

import app_updater


BASE_DIR = pathlib.Path(__file__).parent


def _load_app_module():
    fake_core = types.ModuleType("main")
    fake_core._name = "Zc 测试"
    fake_core._version = "V2.3.0"
    fake_core._version_number = "2.3.0"
    fake_core.BASE_DIR = BASE_DIR
    fake_core.user_name_list = ["乘客1"]
    fake_core.request_set_current_user = lambda _nickname: True
    fake_webview = types.ModuleType("webview")
    module_path = BASE_DIR / "webview_app.py"
    spec = importlib.util.spec_from_file_location("webview_app_gate_test", module_path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"main": fake_core, "webview": fake_webview}):
        spec.loader.exec_module(module)
    return module


class WebViewGateTests(unittest.TestCase):
    @staticmethod
    def _app(module):
        app = module.WebViewApp.__new__(module.WebViewApp)
        app.gate_lock = module.threading.RLock()
        app.closed = False
        app.startup_complete = False
        app.gate_state = {"phase": "ready", "message": "ok"}
        app.startup_active = False
        app.update_policy = {"minimum_supported_version": "2.3.0"}
        app.update_offer = None
        app.windows = {"gate": Mock()}
        app.hotkey_listener = None
        app.hotkey_start_lock = module.threading.RLock()
        app.settings_open = False
        app.nickname = "乘客1"
        app.last_synced_user = None
        app.upload_queue = Mock()
        return app

    def test_passenger_sync_failure_is_actionable_and_retry_requires_recheck(self):
        module = _load_app_module()
        app = self._app(module)
        app.create_window = Mock()
        with patch.object(module.core, "request_set_current_user", return_value=False):
            result = app.action("gate", "continue", {})

        self.assertTrue(result["failed"])
        self.assertEqual(app.gate_state["phase"], "error")
        self.assertIn("同步当前乘客", app.gate_state["message"])
        app.create_window.assert_not_called()
        with self.assertRaisesRegex(ValueError, "尚未允许进入"):
            app.action("gate", "continue", {})

        def online_recheck():
            app.gate_state = {"phase": "ready", "message": "已重新验证"}
            return True

        with patch.object(app, "_begin_startup_check", side_effect=online_recheck) as recheck:
            self.assertEqual(app.action("gate", "retry", {}), {"started": True})
        recheck.assert_called_once()

    def test_failed_window_and_hotkey_initialization_roll_back_for_safe_retry(self):
        module = _load_app_module()
        app = self._app(module)
        app.create_window = Mock(side_effect=RuntimeError("主窗口创建失败"))
        with patch.object(module.core, "request_set_current_user", return_value=True):
            first = app.action("gate", "enter", {})
        self.assertTrue(first["failed"])
        self.assertEqual(app.gate_state["phase"], "error")
        self.assertFalse(app.startup_complete)
        self.assertNotIn("main", app.windows)

        main_window = Mock()

        def create_main(view):
            self.assertEqual(view, "main")
            app.windows["main"] = main_window

        app.create_window.side_effect = create_main

        def online_recheck():
            app.gate_state = {"phase": "ready", "message": "已重新验证"}
            return True

        with patch.object(app, "start_hotkeys", side_effect=RuntimeError("快捷键注册失败")):
            with patch.object(app, "_begin_startup_check", side_effect=online_recheck):
                second = app.action("gate", "retry", {})
                self.assertEqual(second, {"started": True})
                failed_entry = app.action("gate", "enter", {})

        self.assertTrue(failed_entry["failed"])
        self.assertEqual(app.gate_state["phase"], "error")
        self.assertFalse(app.startup_complete)
        self.assertNotIn("main", app.windows)
        main_window.destroy.assert_called_once()

        with patch.object(app, "_begin_startup_check", side_effect=online_recheck):
            app.action("gate", "retry", {})
        app.start_hotkeys = Mock()
        with patch.object(module.core, "request_set_current_user", return_value=True), \
             patch.object(module.threading, "Timer") as timer:
            entered = app.action("gate", "continue", {})
        self.assertEqual(entered, {"entered": True})
        self.assertTrue(app.startup_complete)
        self.assertEqual(app.gate_state["phase"], "entered")
        self.assertIs(app.windows["main"], main_window)
        self.assertEqual(timer.call_args.args[1], app.windows["gate"].destroy)

    def test_exit_during_passenger_sync_prevents_main_window_creation(self):
        module = _load_app_module()
        app = self._app(module)
        app.create_window = Mock()

        def close_before_sync_returns(_nickname):
            app.action("gate", "exit", {})
            return True

        with patch.object(module.core, "request_set_current_user",
                          side_effect=close_before_sync_returns):
            result = app.action("gate", "continue", {})
        self.assertTrue(result["failed"])
        self.assertTrue(app.closed)
        app.create_window.assert_not_called()
        self.assertNotIn("main", app.windows)

    def test_stale_destroyed_gate_callback_does_not_close_active_app(self):
        module = _load_app_module()
        app = self._app(module)
        current_gate = app.windows["gate"]
        stale_gate = Mock()
        app.close = Mock()
        app._window_closed("gate", stale_gate)
        app.close.assert_not_called()
        self.assertIs(app.windows["gate"], current_gate)

    def test_gate_window_uses_pywebview_served_local_page_for_bridge(self):
        module = _load_app_module()
        app = self._app(module)
        app.windows.clear()
        window = Mock()

        class ClosedEvent:
            def __iadd__(self, _callback):
                return self

        window.events.closed = ClosedEvent()
        create_window = Mock(return_value=window)
        with patch.object(module.webview, "create_window", create_window, create=True):
            app.create_window("gate")

        self.assertEqual(create_window.call_args.args[1], module.GATE_UI_PATH)
        self.assertFalse(create_window.call_args.args[1].startswith("file://"))

    def test_official_version_hint_failure_does_not_block_supported_startup(self):
        module = _load_app_module()
        app = self._app(module)
        stderr = io.StringIO()
        with (
            patch.object(module, "recover_incomplete_update"),
            patch.object(module, "fetch_update_policy", return_value={
                "minimum_supported_version": "2.3.0",
                "message": "需要更新",
            }),
            patch.object(module, "read_update_failure", return_value=None),
            patch.object(
                module, "fetch_official_version",
                side_effect=ValueError("官方 version.py 请求失败"),
            ) as version_request,
            patch.object(app_updater, "_release_data") as release_request,
            contextlib.redirect_stderr(stderr),
        ):
            app._run_startup_check()

        version_request.assert_called_once()
        release_request.assert_not_called()
        self.assertEqual(app.gate_state["phase"], "ready")
        self.assertIn("不影响已达标客户端启动", stderr.getvalue())


class GateStyleTests(unittest.TestCase):
    def test_dark_mode_is_applied_before_local_styles_without_storage(self):
        html = (BASE_DIR / "webview_ui/gate.html").read_text(encoding="utf-8")
        stylesheet = (BASE_DIR / "webview_ui/fonts/fusion-pixel.css").read_text(encoding="utf-8")
        root = BASE_DIR / "webview_ui/fonts"

        self.assertLess(html.index('<html lang="zh-CN" class="dark gate-page">'),
                        html.index('<link rel="stylesheet" href="fonts/fusion-pixel.css">'))
        self.assertNotIn("localStorage", html)
        self.assertIn('<link rel="stylesheet" href="gate.css">', html)
        urls = re.findall(r"""url\(["']?([^)"']+\.woff2)["']?\)""", stylesheet)
        self.assertEqual(len(urls), 3)
        for url in urls:
            self.assertTrue((root / url).is_file())
        self.assertNotIn("https://", (BASE_DIR / "webview_ui/gate.css").read_text(encoding="utf-8"))
        self.assertIn("html.dark.gate-page", (BASE_DIR / "webview_ui/gate.css").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
