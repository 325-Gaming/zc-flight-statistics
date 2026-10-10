"""Main-window ON AIR switch behavior without native windows."""

import unittest
from unittest.mock import Mock, patch

from test_webview_gate import _load_app_module


class WebViewOnAirTests(unittest.TestCase):
    def test_style_list_failure_preserves_loaded_activity(self):
        module = _load_app_module()
        app = module.WebViewApp.__new__(module.WebViewApp)
        app.page_style = "classic"
        app.page_is_active = False
        module.core.client = object()
        module.core.get_page_display_api_url = "https://example.test/page-display"
        module.core.get_page_style_list_api_url = "https://example.test/page-style-list"
        module.core.login_token = "test-token"

        with patch.object(
            module, "get_page_display_settings",
            return_value={"is_active": True, "page_style": "custom"},
        ), patch.object(
            module, "get_available_page_style_list",
            side_effect=module.httpx.ConnectError("offline"),
        ):
            app._load_style()

        self.assertTrue(app.page_is_active)
        self.assertEqual(app.page_style, module.DEFAULT_PAGE_STYLE)

    def test_switch_updates_only_activity_in_latest_page_settings(self):
        module = _load_app_module()
        app = module.WebViewApp.__new__(module.WebViewApp)
        app.logged_out = False
        app.page_is_active = False
        app._emit_main = Mock()
        app._main_state = Mock(return_value={"page_is_active": True})
        module.core.client = object()
        module.core.get_page_display_api_url = "https://example.test/page-display"
        module.core.set_page_display_api_url = "https://example.test/page-display/set"
        module.core.login_token = "test-token"
        latest = {"is_active": False, "page_style": "classic", "other": "preserved"}
        saved = {**latest, "is_active": True}

        with patch.object(module, "get_page_display_settings", return_value=latest) as get_settings, \
                patch.object(module, "set_page_display_settings", return_value=saved) as set_settings:
            result = app.action("main", "on_air", {"enabled": True})

        self.assertEqual(result, {"page_is_active": True})
        self.assertTrue(app.page_is_active)
        self.assertEqual(latest, saved)
        get_settings.assert_called_once_with(
            module.core.client, module.core.get_page_display_api_url, module.core.login_token,
        )
        set_settings.assert_called_once_with(
            module.core.client, module.core.set_page_display_api_url,
            module.core.login_token, saved,
        )
        app._emit_main.assert_called_once_with()

    def test_invalid_switch_value_does_not_request_settings(self):
        module = _load_app_module()
        app = module.WebViewApp.__new__(module.WebViewApp)
        app.logged_out = False

        with patch.object(module, "get_page_display_settings") as get_settings:
            with self.assertRaisesRegex(ValueError, "必须为布尔值"):
                app.action("main", "on_air", {"enabled": "true"})

        get_settings.assert_not_called()


if __name__ == "__main__":
    unittest.main()
