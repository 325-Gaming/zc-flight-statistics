"""Check that a denied login can receive a later permission grant."""

import importlib.util
import json
import pathlib
import sys
import types
import unittest
from unittest.mock import MagicMock, patch


class LoginWindowTests(unittest.TestCase):
    def test_same_session_is_rechecked_after_permission_grant(self):
        fake_webview = types.ModuleType('webview')
        window = MagicMock()
        window.evaluate_js.side_effect = lambda script: (
            json.dumps({'identifier': '12345', 'token': 'secret'})
            if script.startswith('JSON.stringify') else None
        )
        fake_webview.create_window = MagicMock(return_value=window)
        fake_webview.start = lambda callback, **_kwargs: callback()
        module_path = pathlib.Path(__file__).with_name('login_window.py')
        spec = importlib.util.spec_from_file_location('login_window_test', module_path)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'webview': fake_webview}):
            spec.loader.exec_module(module)

        denied = {'status': 'success'}
        granted = {'status': 'success', 'permission_code_list': ['zc.flight_user']}
        closed = MagicMock()
        closed.is_set.return_value = False
        with patch.object(module, 'load_session', return_value=None), \
             patch.object(module, 'clear_session'), \
             patch.object(module, 'get_login_info', side_effect=[denied, granted]) as check, \
             patch.object(module, 'save_session') as save, \
             patch.object(module.threading, 'Event', return_value=closed), \
             patch.object(module.time, 'monotonic', side_effect=[0, 0, 10, 31]), \
             patch.object(module.os, 'execv'):
            module.ensure_login()

        self.assertEqual(check.call_count, 2)
        save.assert_called_once_with('12345', 'secret')
        window.destroy.assert_called_once_with()
        alerts = [call for call in window.evaluate_js.call_args_list
                  if call.args[0].startswith('alert(')]
        self.assertEqual(len(alerts), 1)


if __name__ == '__main__':
    unittest.main()
