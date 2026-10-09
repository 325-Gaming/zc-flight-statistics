"""Offline geometry and capture coordination checks without a native window."""

import ast
import inspect
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from result_overlay import ResultOverlay, overlay_cells, overlay_geometry
from utils import crop_to_16_9_center, gacha10_horizontal_bounds


class ResultOverlayTests(unittest.TestCase):
    def test_geometry_stays_below_crop_and_inside_selected_monitor(self):
        for width, height in [(1920, 1080), (2560, 1440), (3440, 1440), (1200, 1920)]:
            monitor = dict(left=-width, top=-200, width=width, height=height)
            x, y, w, h = overlay_geometry(monitor)
            crop_height = min(height, int(width * 9 / 16))
            bottom = monitor['top'] + (height - crop_height) // 2 + int(crop_height * .8)
            self.assertEqual((x, w), (monitor['left'], width))
            self.assertEqual(y, bottom + 31)
            self.assertEqual(y + h, monitor['top'] + height)

    def test_cells_span_recognition_area_edges(self):
        cells = overlay_cells(dict(width=1920, height=1080))
        self.assertEqual(gacha10_horizontal_bounds(1920), (42, 1878))
        self.assertEqual(cells[0][0], 42)
        self.assertEqual(sum(cells[-1]), 1878)
        self.assertEqual(len(cells), 10)
        for i in range(1, 10):
            self.assertEqual(sum(cells[i - 1]), cells[i][0])
        self.assertLessEqual(max(w for _, w in cells) - min(w for _, w in cells), 1)

    def test_recognition_area_edges_follow_center_crop(self):
        for width, height in [(2560, 1440), (3440, 1440), (1200, 1920), (1921, 1081)]:
            cropped = crop_to_16_9_center(Image.new('RGB', (width, height)))
            crop_left = (width - cropped.width) // 2
            left, right = gacha10_horizontal_bounds(cropped.width)
            cells = overlay_cells(dict(width=width, height=height))
            self.assertEqual(cells[0][0], crop_left + left)
            self.assertEqual(sum(cells[-1]), crop_left + right)

    def test_results_preserve_order_and_names_with_spaces(self):
        overlay = ResultOverlay()
        names = ['干员 A'] + [f'干员{i}' for i in range(1, 10)]
        overlay.show_result(names)
        names[0] = '已更改'
        self.assertEqual(overlay.results, ('干员 A',) + tuple(f'干员{i}' for i in range(1, 10)))

    def test_refresh_converts_tcl_distance_and_fits_font_on_one_line(self):
        # Exercise the UI callback without creating a Windows window. The
        # distance deliberately cannot be converted by Python's int().
        node = next(node for node in ast.walk(ast.parse(inspect.getsource(ResultOverlay)))
                    if isinstance(node, ast.FunctionDef) and node.name == 'refresh')
        label = Mock()
        distance = object()
        label.cget.return_value = distance
        label.winfo_pixels.return_value = 2
        label.winfo_reqheight.return_value = 50
        font = Mock()
        size = 32

        def configure(**values):
            nonlocal size
            size = values['size']

        font.configure.side_effect = configure
        font.cget.side_effect = lambda _key: size
        font.measure.side_effect = lambda _text: size * 10
        overlay = ResultOverlay()
        overlay.enabled = True
        overlay.monitor = dict(width=1920, height=1080, left=0, top=0)
        overlay.results = ('薇薇安娜',)
        namespace = dict(self=overlay, hidden=0, user32=Mock(), hwnd=1,
                         overlay_geometry=Mock(return_value=(0, 900, 1920, 180)),
                         overlay_cells=Mock(return_value=[(42, 212)]),
                         labels=[label], fonts=[font], waiting_label=Mock(), root=Mock(),
                         wintypes=Mock())
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<refresh-test>', 'exec'), namespace)
        namespace['refresh']()
        label.winfo_pixels.assert_called_once_with(distance)
        self.assertEqual(size, 20)
        label.configure.assert_called_once_with(text='薇薇安娜', wraplength=0)
        # A later short result must grow back to the default size.
        font.measure.side_effect = lambda _text: size * 2
        namespace['refresh']()
        self.assertEqual(size, 32)

    def test_capture_hides_first_and_restores_after_failure(self):
        overlay = ResultOverlay()
        overlay.thread = Mock()
        overlay.thread.is_alive.return_value = True
        events = []

        def consume(item):
            command, ready = item
            events.append(command)
            if ready:
                ready.set()

        overlay.commands.put = consume
        with self.assertRaisesRegex(ValueError, 'capture failed'):
            with overlay.hidden_for_capture():
                self.assertEqual(events, ['hide'])
                raise ValueError('capture failed')
        self.assertEqual(events, ['hide', 'resume'])

    def test_disabled_capture_does_not_wait_or_create_window(self):
        overlay = ResultOverlay()
        with overlay.hidden_for_capture():
            self.assertIsNone(overlay.thread)
        self.assertTrue(overlay.commands.empty())

    def test_non_windows_cannot_enable_overlay(self):
        with patch('result_overlay.sys.platform', 'darwin'):
            with self.assertRaisesRegex(ValueError, 'Windows'):
                ResultOverlay().configure(True, dict(left=0, top=0, width=1920, height=1080))


if __name__ == '__main__':
    unittest.main()
