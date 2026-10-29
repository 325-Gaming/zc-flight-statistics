import json
import pathlib
import tempfile
import unittest
from unittest.mock import Mock, patch

import httpx

from live_page_settings import request_live_page
from test_webview_profile import WebViewProfileTests


class LivePageSettingsTests(unittest.TestCase):
    def test_management_uses_existing_origin_and_encodes_id(self):
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(200, json={'status': 'success'})
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            request_live_page(client, 'https://example.test/api/gachalog-zc/set-current-user', 'test-token', 'set-live', live_id='test & value', payload={'name': '活动'})
        request = requests[0]
        self.assertEqual(request.url.path, '/api/gachalog-zc/set-live')
        self.assertEqual(request.url.params['live_id'], 'test & value')
        self.assertEqual(json.loads(request.content), {'name': '活动'})

    def test_upstream_errors_are_not_replaced_by_empty_lists(self):
        with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(503))) as client:
            with self.assertRaises(httpx.HTTPStatusError):
                request_live_page(client, 'https://example.test/set-current-user', 'test-token', 'get-live-list')

    def test_select_persists_live_id_and_protects_open_settings_window(self):
        module = WebViewProfileTests._load_app_module()
        app = module.WebViewApp.__new__(module.WebViewApp)
        app.logged_out = False
        app.live_id = ''
        app.windows = {}
        app._load_style = Mock()
        app._emit_main = Mock()
        app._main_state = Mock(return_value={})
        app._statistics_state = Mock(side_effect=lambda: {'live_list': [{'live_id': 'one'}], 'live_id': app.live_id})
        module.core.client = object()
        module.core.login_token = 'test-token'
        module.core.get_page_display_api_url = 'https://example.test/get-page-display'
        module.get_page_display_settings = Mock(return_value={'page_style': 'classic', 'is_active': False})
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / 'config.json'
            path.write_text('{"event_name": "活动"}')
            module.core.CONFIG_PATH = path
            module.core.config = {'event_name': '活动'}
            result = app.action('statistics', 'select', {'live_id': 'one'})
            self.assertEqual(result['live_id'], 'one')
            self.assertEqual(json.loads(path.read_text()), {'event_name': '活动', 'live_id': 'one'})
            self.assertEqual(module.core.config['live_id'], 'one')
            app.windows['page'] = object()
            with self.assertRaisesRegex(RuntimeError, '关闭直播页面设置'):
                app.action('statistics', 'select', {'live_id': ''})
            self.assertEqual(json.loads(path.read_text())['live_id'], 'one')

    def test_on_air_targets_selected_configuration(self):
        module = WebViewProfileTests._load_app_module()
        app = module.WebViewApp.__new__(module.WebViewApp)
        app.logged_out = False
        app.live_id = 'one'
        app._emit_main = Mock()
        app._main_state = Mock(return_value={})
        module.core.client = object()
        module.core.login_token = 'test-token'
        module.core.get_page_display_api_url = 'https://example.test/get-page-display'
        module.core.set_page_display_api_url = 'https://example.test/set-page-display'
        settings = {'is_active': False, 'other': 'preserved'}
        with patch.object(module, 'get_page_display_settings', return_value=settings) as get_settings, patch.object(module, 'set_page_display_settings', return_value={**settings, 'is_active': True}) as set_settings:
            app.action('main', 'on_air', {'enabled': True})
        self.assertEqual(get_settings.call_args.kwargs, {'live_id': 'one'})
        self.assertEqual(set_settings.call_args.kwargs, {'live_id': 'one'})
        self.assertEqual(set_settings.call_args.args[-1], {'is_active': True, 'other': 'preserved'})


if __name__ == '__main__':
    unittest.main()
