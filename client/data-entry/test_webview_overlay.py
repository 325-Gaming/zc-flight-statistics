"""Main-window overlay switch persistence without native windows."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from test_webview_gate import _load_app_module


class WebViewOverlayTests(unittest.TestCase):
    def test_switch_persists_and_uses_selected_monitor(self):
        module = _load_app_module()
        app = module.WebViewApp.__new__(module.WebViewApp)
        app.logged_out = False
        app._emit_main = Mock()
        app._main_state = Mock(return_value={"updated": True})
        module.core.capture = Mock(monitors=[{}, {"left": -1920, "width": 1920}])
        module.core.target_monitor_id = 1
        with tempfile.TemporaryDirectory() as directory:
            module.core.CONFIG_PATH = Path(directory) / 'config.json'
            module.core.config = {"pool_name": "测试卡池", "show_result_overlay": False}
            module.core.CONFIG_PATH.write_text(json.dumps(module.core.config))
            with patch.object(module.sys, 'platform', 'win32'), \
                    patch.object(module, 'result_overlay') as overlay:
                for enabled in (True, False):
                    self.assertEqual(app.action('main', 'overlay', {'enabled': enabled}), {"updated": True})
                    saved = json.loads(module.core.CONFIG_PATH.read_text())
                    self.assertEqual(saved, {"pool_name": "测试卡池", "show_result_overlay": enabled})
                    self.assertEqual(module.core.config['show_result_overlay'], enabled)
                    overlay.configure.assert_called_with(enabled, module.core.capture.monitors[1])

    def test_invalid_or_unsupported_switch_does_not_write_config(self):
        module = _load_app_module()
        app = module.WebViewApp.__new__(module.WebViewApp)
        app.logged_out = False
        module.core.CONFIG_PATH = Mock()
        with patch.object(module.sys, 'platform', 'darwin'):
            for value in ('true', True):
                with self.assertRaises(ValueError):
                    app.action('main', 'overlay', {'enabled': value})
        module.core.CONFIG_PATH.open.assert_not_called()
