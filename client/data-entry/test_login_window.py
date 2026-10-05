"""Check the denied-login page and its logout action."""

import importlib.util
import json
import pathlib
import sys
import types
import unittest
from unittest.mock import MagicMock, patch


class LoginWindowTests(unittest.TestCase):
    def test_denied_login_shows_permission_page(self):
        fake_webview = types.ModuleType('webview')
        window = MagicMock()
        window.evaluate_js.return_value = json.dumps({
            'identifier': '12345', 'token': 'secret',
        })
        fake_webview.create_window = MagicMock(return_value=window)
        fake_webview.start = lambda callback, **_kwargs: callback()
        module_path = pathlib.Path(__file__).with_name('login_window.py')
        spec = importlib.util.spec_from_file_location('login_window_test', module_path)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'webview': fake_webview}):
            spec.loader.exec_module(module)

        with patch.object(module, 'load_session', return_value=None), \
             patch.object(module, 'clear_session'), \
             patch.object(module, 'get_login_info', return_value={'status': 'success'}), \
             patch.object(module, 'save_session') as save, \
             self.assertRaises(SystemExit):
            module.ensure_login()

        save.assert_called_once_with('12345', 'secret')
        scripts = [call.args[0] for call in window.evaluate_js.call_args_list]
        self.assertIn(module.DENIED_PAGE_SCRIPT, scripts)
        self.assertIn('当前账号没有Zc航空数据录入权限', module.DENIED_PAGE_SCRIPT)
        self.assertIn('退出登录', module.DENIED_PAGE_SCRIPT)
        self.assertIn('el-button el-button--primary', module.DENIED_PAGE_SCRIPT)
        window.load_html.assert_not_called()
        window.load_url.assert_not_called()
        self.assertEqual(fake_webview.create_window.call_args.kwargs['js_api'].session.token,
                         'secret')

    def test_saved_denied_session_reopens_permission_page_without_logout(self):
        fake_webview = types.ModuleType('webview')
        window = MagicMock()
        window.evaluate_js.side_effect = lambda script: (
            True if script == "document.readyState === 'complete' && location.origin === 'https://yubo.run'"
            else None
        )
        fake_webview.create_window = MagicMock(return_value=window)
        fake_webview.start = lambda callback, **_kwargs: callback()
        module_path = pathlib.Path(__file__).with_name('login_window.py')
        spec = importlib.util.spec_from_file_location('login_window_test', module_path)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'webview': fake_webview}):
            spec.loader.exec_module(module)

        saved = module.SessionCredentials('12345', 'secret', 0)
        with patch.object(module, 'load_session', return_value=saved), \
             patch.object(module, 'get_login_info', return_value={'status': 'success'}), \
             patch.object(module, 'clear_session') as clear, \
             self.assertRaises(SystemExit):
            module.ensure_login()

        clear.assert_not_called()
        self.assertEqual([call.args[0] for call in window.evaluate_js.call_args_list], [
            module.DENIED_PAGE_READY_SCRIPT, module.DENIED_PAGE_SCRIPT,
        ])
        self.assertIs(fake_webview.create_window.call_args.kwargs['js_api'].session, saved)

    def test_logout_revokes_denied_session_and_closes_window(self):
        fake_webview = types.ModuleType('webview')
        fake_webview.create_window = MagicMock()
        fake_webview.start = MagicMock()
        module_path = pathlib.Path(__file__).with_name('login_window.py')
        spec = importlib.util.spec_from_file_location('login_window_test', module_path)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'webview': fake_webview}):
            spec.loader.exec_module(module)

        bridge = module.LoginBridge()
        bridge.window = MagicMock()
        bridge.session = module.SessionCredentials('12345', 'secret', 0)
        with patch.object(module, 'logout', return_value={'message': '退出登录成功'}) as logout, \
             patch.object(module.threading, 'Timer') as timer:
            self.assertTrue(bridge.logout())
        logout.assert_called_once_with(bridge.session)
        timer.assert_called_once_with(0.2, bridge.window.destroy)
        timer.return_value.start.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
