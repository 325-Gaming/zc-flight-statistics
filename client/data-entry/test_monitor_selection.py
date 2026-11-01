"""Check disconnected-monitor recovery without accessing real displays or config."""

import ast
import pathlib
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock


class MonitorSelectionTests(unittest.TestCase):
    def test_missing_saved_display_does_not_configure_overlay(self):
        tree = ast.parse(pathlib.Path(__file__).with_name('main.py').read_text())
        node = next(item for item in tree.body if isinstance(item, ast.If)
            and ast.unparse(item.test) == '0 <= target_monitor_id < len(capture.monitors)')
        for target, valid in [(3, False), (1, True), (-1, False)]:
            overlay = Mock()
            namespace = {'capture': SimpleNamespace(monitors=[{}, {}]), 'target_monitor_id': target,
                'result_overlay': overlay, 'config': {'show_result_overlay': False},
                'sys': SimpleNamespace(platform='win32'), 'print': Mock(), 'monitor_error': ''}
            exec(compile(ast.Module(body=[node], type_ignores=[]), '<monitor-init>', 'exec'), namespace)
            self.assertEqual(overlay.configure.called, valid)
            if not valid:
                self.assertIn('已不可用', namespace['monitor_error'])

    def test_capture_checks_current_session_display_list(self):
        tree = ast.parse(pathlib.Path(__file__).with_name('main.py').read_text())
        node = next(item for item in tree.body if isinstance(item, ast.ClassDef) and item.name == 'MultiMonitorCapture')
        local_capture = MagicMock()
        local_capture.__enter__.return_value.monitors = [{}, {}]
        overlay = MagicMock()
        namespace = {'mss': SimpleNamespace(mss=lambda: local_capture),
            'result_overlay': overlay, 'time': SimpleNamespace(time=lambda: 0)}
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<capture-monitor>', 'exec'), namespace)
        capture = namespace['MultiMonitorCapture'].__new__(namespace['MultiMonitorCapture'])
        capture.monitors = [{}, {}, {}, {}]
        with self.assertRaisesRegex(ValueError, '已不可用'):
            capture.capture_monitor(3)
        local_capture.__enter__.return_value.grab.assert_not_called()
