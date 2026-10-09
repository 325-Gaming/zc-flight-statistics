"""Exercise detection result reset without loading live client services."""

import ast
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, call

import numpy as np
from PIL import Image

from utils import expand_to_square, process_to_16_9


class CaptureResultResetTests(unittest.TestCase):
    def test_each_detection_clears_old_results_before_capture(self):
        source = Path(__file__).with_name('main.py').read_text(encoding='utf-8')
        node = next(node for node in ast.parse(source).body
                    if isinstance(node, ast.FunctionDef) and node.name == 'capture_and_predict')
        for classification in (0, 1, 2, 'capture-error'):
            with self.subTest(classification=classification), tempfile.TemporaryDirectory() as directory:
                app, overlay, capture = Mock(), Mock(), Mock()
                parent = Mock()
                parent.attach_mock(overlay, 'overlay')
                parent.attach_mock(app, 'app')
                parent.attach_mock(capture, 'capture')
                if classification == 'capture-error':
                    capture.capture_monitor.side_effect = RuntimeError('capture failed')
                else:
                    capture.capture_monitor.return_value = Image.new('RGB', (192, 108))
                image_model = Mock()
                image_model.get_inputs.return_value = [Mock(name="image-input")]
                image_model.run.return_value = [np.eye(3)[[0 if classification == 'capture-error' else classification]]]
                operator_model = Mock()
                operator_model.get_inputs.return_value = [Mock(name="operator-input")]
                operator_model.run.return_value = [np.ones((10, 1))]
                namespace = dict(
                    app=app, result_overlay=overlay, capture=capture,
                    target_monitor_id=1, time=time, Image=Image, np=np,
                    process_to_16_9=process_to_16_9, expand_to_square=expand_to_square,
                    im_w=128, im_h=128, model_image_type=image_model,
                    model_gacha10=operator_model, operator_id_to_name={0: '角峰'},
                    seperate_image_gacha10=lambda _image: np.zeros((10, 64, 32, 3)),
                    BASE_DIR=Path(directory),
                )
                exec(compile(ast.Module(body=[node], type_ignores=[]), '<capture-test>', 'exec'), namespace)
                if classification == 'capture-error':
                    with self.assertRaisesRegex(RuntimeError, 'capture failed'):
                        namespace['capture_and_predict']()
                else:
                    namespace['capture_and_predict']()
                self.assertEqual(parent.mock_calls[:3], [
                    call.overlay.show_result([''] * 10),
                    call.app.show_result(''),
                    call.capture.capture_monitor(1, is_save=False),
                ])
                if classification == 2:
                    overlay.show_result.assert_called_with(['角峰'] * 10)
                    app.show_result.assert_called_with(' '.join(['角峰'] * 10))
                    app.enqueue_gacha_result.assert_called_once()
                else:
                    overlay.show_result.assert_called_once_with([''] * 10)
                    app.show_result.assert_called_once_with('')
                    app.enqueue_gacha_result.assert_not_called()
