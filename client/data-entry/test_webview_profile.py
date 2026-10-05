"""Match the personal center's title and selected nickname in the menu bar."""

import importlib.util
import pathlib
import sys
import types
import unittest
from unittest.mock import Mock, patch


class WebViewProfileTests(unittest.TestCase):
    @staticmethod
    def _load_app_module():
        fake_core = types.ModuleType("main")
        fake_core._name = "Zc 测试"
        fake_core._version = "V0"
        fake_core.BASE_DIR = pathlib.Path(__file__).parent
        fake_webview = types.ModuleType("webview")
        module_path = pathlib.Path(__file__).with_name("webview_app.py")
        spec = importlib.util.spec_from_file_location("webview_app_profile_test", module_path)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"main": fake_core, "webview": fake_webview}):
            spec.loader.exec_module(module)
        return module

    def test_selected_nickname_uses_personal_center_fields(self):
        module = self._load_app_module()
        info = {
            "status": "success", "permission_code_list": ["zc.flight_user"],
            "user_id": 123, "title_adj": "资深", "title_title": "机长",
            "nickname": "arknights_nickname_clear",
            "bilibili": {"nickname": "哔哩昵称"},
            "arknights": {"nickname": "博士#1234"},
        }
        self.assertEqual(module._captain_profile(info), {
            "title": "资深机长", "nickname": "博士",
        })
        info["nickname"] = "bilibili_nickname"
        self.assertEqual(module._captain_profile(info)["nickname"], "哔哩昵称")
        info["nickname"] = "null"
        self.assertEqual(module._captain_profile(info)["nickname"], "")
        info["nickname"] = "arknights_nickname"
        info["user_id"] = None
        self.assertEqual(module._captain_profile(info)["nickname"], "")

        info["user_id"] = 123
        app = module.WebViewApp.__new__(module.WebViewApp)
        module.core.login_token = object()
        module.core.client = object()
        with patch.object(module, "get_login_info", return_value=info) as request:
            app._load_captain_profile()
        request.assert_called_once_with(module.core.login_token, client=module.core.client)
        self.assertEqual(app.captain_profile, {
            "title": "资深机长", "nickname": "博士#1234",
        })

    def test_profile_requires_valid_flight_permission(self):
        module = self._load_app_module()
        self.assertIsNone(module._captain_profile({"status": "success"}))
        app = module.WebViewApp.__new__(module.WebViewApp)
        module.core.login_token = object()
        module.core.client = object()
        with patch.object(module, "get_login_info", side_effect=module.httpx.ConnectError("offline")) as request:
            app._load_captain_profile()
        request.assert_called_once_with(module.core.login_token, client=module.core.client)
        self.assertIsNone(app.captain_profile)


if __name__ == "__main__":
    unittest.main()
