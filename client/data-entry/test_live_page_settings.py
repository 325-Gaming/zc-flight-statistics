import json
import pathlib
import tempfile
import unittest
from unittest.mock import Mock, patch

import httpx

from live_page_settings import request_live_page
from test_webview_profile import WebViewProfileTests


class LivePageSettingsTests(unittest.TestCase):
    def test_statistics_uses_server_pool_list_for_dropdown(self):
        module = WebViewProfileTests._load_app_module()
        app = module.WebViewApp.__new__(module.WebViewApp)
        app.live_id = ''
        app.activity_list = []
        module.core.client = object()
        module.core.login_token = 'test-token'
        module.core.set_current_user_api_url = 'https://example.test/set-current-user'
        module.core.get_pool_list_api_url = 'https://example.test/get-pool-list'
        module.core.statistics_page_url = 'https://example.test/live'
        module.core.activity_id = 'activity'
        module.core.event_name = '活动'
        module.core.pool_name = '当前卡池'
        with patch.object(module, 'request_live_page', return_value={
            'live_list': [], 'user_id': '10001', 'is_admin': False,
            'default_live_id': '',
        }), patch.object(module, 'get_page_pool_settings', return_value={
            'pool_name_list': ('新卡池', '当前卡池'),
        }) as get_pool_list:
            state = app._statistics_state()
        self.assertEqual(state['pool_names'], ('新卡池', '当前卡池'))
        get_pool_list.assert_called_once_with(
            module.core.client, module.core.get_pool_list_api_url, 'test-token',
        )

        script = (pathlib.Path(__file__).parent / 'webview_ui/app.js').read_text(
            encoding='utf-8',
        )
        self.assertIn('<select id="live-pool" required>${poolOptions}</select>', script)
        self.assertNotIn('<input id="live-pool"', script)

    def test_management_uses_existing_origin_and_encodes_id(self):
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(200, json={'status': 'success'})
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            request_live_page(client, 'https://example.test/api/zc-flight/gachalog/set-current-user', 'test-token', 'set-live', live_id='test & value', payload={'name': '活动'})
        request = requests[0]
        self.assertEqual(request.url.path, '/api/zc-flight/live/set')
        self.assertEqual(request.url.params['live_id'], 'test & value')
        self.assertEqual(json.loads(request.content), {'name': '活动'})

    def test_management_routes_preserve_proxy_prefix_across_namespaces(self):
        routes = {
            'get-activity-list': 'activity/get-list',
            'get-live-list': 'live/get-list',
            'create-live': 'live/create',
            'set-live': 'live/set',
            'set-live-editor': 'live/set-editor',
            'remove-live': 'live/remove',
            'set-default-live': 'live/set-default',
        }
        for action, path in routes.items():
            with self.subTest(action=action):
                requests = []
                def handler(request):
                    requests.append(request)
                    return httpx.Response(200, json={
                        'status': 'success', 'activity_list': [], 'live_list': [],
                        'user_id': '10001', 'is_admin': False, 'default_live_id': '',
                    })
                with httpx.Client(transport=httpx.MockTransport(handler)) as client:
                    request_live_page(
                        client, 'https://example.test/proxy/api/zc-flight/gachalog/set-current-user',
                        'test-token', action,
                        payload=None if action.startswith('get-') else {},
                    )
                self.assertEqual(requests[0].url.path, '/proxy/api/zc-flight/' + path)
                self.assertEqual(requests[0].method, 'GET' if action.startswith('get-') else 'POST')

    def test_upstream_errors_are_not_replaced_by_empty_lists(self):
        with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(503))) as client:
            with self.assertRaises(httpx.HTTPStatusError):
                request_live_page(client, 'https://example.test/set-current-user', 'test-token', 'get-live-list')

    def test_activity_list_requires_scoped_role_data(self):
        valid = {
            'status': 'success',
            'activity_list': [{
                'activity_id': '11111111-1111-1111-1111-111111111111',
                'name': '测试活动',
                'role': 'captain',
            }],
        }
        with httpx.Client(transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=valid)
        )) as client:
            self.assertEqual(
                request_live_page(
                    client, 'https://example.test/set-current-user', 'test-token',
                    'get-activity-list',
                ),
                valid,
            )
        invalid = {**valid, 'activity_list': [{**valid['activity_list'][0], 'role': 'admin'}]}
        with httpx.Client(transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=invalid)
        )) as client:
            with self.assertRaisesRegex(ValueError, '活动列表项目无效'):
                request_live_page(
                    client, 'https://example.test/set-current-user', 'test-token',
                    'get-activity-list',
                )

    def test_account_contract_rejects_numeric_and_legacy_ids(self):
        row = {'live_id': 'live', 'name': '直播', 'activity_id': 'activity',
               'event_name': '活动', 'pool_name': '卡池', 'owner_user_id': '10001',
               'follow_user_id': '9007199254740993', 'editor_user_id_list': ['10002'],
               'fixed_nickname': None, 'is_enabled': True}
        valid = {'live_list': [row], 'user_id': '10001', 'is_admin': False, 'default_live_id': ''}
        cases = [valid, {**valid, 'user_id': 10001},
                 {**valid, 'live_list': [{**row, 'follow_user_id': 10002}]},
                 {**valid, 'live_list': [{**row, 'editor_user_id_list': [2]}]},
                 {'live_list': [], 'operator_id': 1, 'is_admin': False, 'default_live_id': ''}]
        for index, data in enumerate(cases):
            with httpx.Client(transport=httpx.MockTransport(
                lambda _, data=data: httpx.Response(200, json=data)
            )) as client:
                if index == 0:
                    result = request_live_page(client, 'https://example.test/set-current-user',
                                               'token', 'get-live-list')
                    self.assertEqual(result['live_list'][0]['follow_user_id'], '9007199254740993')
                else:
                    with self.assertRaises(ValueError):
                        request_live_page(client, 'https://example.test/set-current-user',
                                          'token', 'get-live-list')

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

    def test_remove_selected_live_clears_persisted_selection(self):
        module = WebViewProfileTests._load_app_module()
        app = module.WebViewApp.__new__(module.WebViewApp)
        app.startup_complete = True
        app.logged_out = False
        app.live_id = 'one'
        app.windows = {}
        app._emit_main = Mock()
        app._statistics_state = Mock(return_value={'live_list': [], 'live_id': ''})
        module.core.client = object()
        module.core.login_token = 'test-token'
        module.core.get_page_display_api_url = 'https://example.test/get-page-display'
        module.core.set_current_user_api_url = 'https://example.test/set-current-user'
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / 'config.json'
            path.write_text('{"live_id": "one", "event_name": "活动"}')
            module.core.CONFIG_PATH = path
            module.core.config = {'live_id': 'one', 'event_name': '活动'}
            with patch.object(module, 'request_live_page', return_value={
                'status': 'success', 'live_id': 'one',
            }) as request, patch.object(module, 'get_page_display_settings', return_value={
                'page_style': 'classic', 'is_active': True,
            }) as get_settings:
                result = app.action('statistics', 'remove', {
                    'live_id': 'one', 'values': {'live_id': 'one'},
                })
            self.assertEqual(result['result']['live_id'], 'one')
            self.assertEqual(app.live_id, '')
            self.assertEqual(module.core.config['live_id'], '')
            self.assertEqual(json.loads(path.read_text())['live_id'], '')
            self.assertEqual(request.call_args.args[-1], 'remove-live')
            self.assertEqual(get_settings.call_args.kwargs, {})
            self.assertTrue(app.page_is_active)
            app._emit_main.assert_called_once_with()

    def test_default_changes_sync_main_only_when_following_server(self):
        for selected_id in ('', 'pinned'):
            for default_id in ('one', ''):
                with self.subTest(selected_id=selected_id, default_id=default_id):
                    module = WebViewProfileTests._load_app_module()
                    app = module.WebViewApp.__new__(module.WebViewApp)
                    app.logged_out = False
                    app.live_id = selected_id
                    app.page_is_active = False
                    app.windows = {'main': object()}
                    app._emit = Mock()
                    app._emit_main = Mock()
                    app._statistics_state = Mock(return_value={})
                    module.core.client = object()
                    module.core.login_token = 'test-token'
                    module.core.set_current_user_api_url = 'https://example.test/set-current-user'
                    module.core.get_page_display_api_url = 'https://example.test/get-page-display'
                    with patch.object(module, 'request_live_page', return_value={
                        'status': 'success', 'live_id': default_id,
                    }), patch.object(module, 'get_page_display_settings', return_value={
                        'page_style': 'custom', 'is_active': True,
                    }) as get_settings:
                        app.action('statistics', 'default', {'values': {'live_id': default_id}})
                    if selected_id:
                        get_settings.assert_not_called()
                        app._emit_main.assert_not_called()
                        self.assertFalse(app.page_is_active)
                    else:
                        self.assertEqual(get_settings.call_args.kwargs, {})
                        self.assertTrue(app.page_is_active)
                        app._emit.assert_called_once_with('main', {'theme': 'custom'})
                        app._emit_main.assert_called_once_with()

    def test_refresh_syncs_selected_configuration_and_propagates_failure(self):
        module = WebViewProfileTests._load_app_module()
        app = module.WebViewApp.__new__(module.WebViewApp)
        app.logged_out = False
        app.live_id = 'one'
        app.page_is_active = False
        app.windows = {}
        app._emit_main = Mock()
        app._statistics_state = Mock(return_value={'live_id': 'one'})
        module.core.client = object()
        module.core.login_token = 'test-token'
        module.core.get_page_display_api_url = 'https://example.test/get-page-display'
        with patch.object(module, 'get_page_display_settings', return_value={
            'page_style': 'classic', 'is_active': True,
        }) as get_settings:
            self.assertEqual(app.action('statistics', 'refresh', {}), {'live_id': 'one'})
        self.assertEqual(get_settings.call_args.kwargs, {'live_id': 'one'})
        self.assertTrue(app.page_is_active)
        app._emit_main.assert_called_once_with()
        app._emit_main.reset_mock()
        with patch.object(module, 'get_page_display_settings', side_effect=httpx.ConnectError('offline')):
            with self.assertRaises(httpx.ConnectError):
                app.action('statistics', 'refresh', {})
        self.assertTrue(app.page_is_active)
        app._emit_main.assert_not_called()

    def test_saved_default_reports_sync_failure_and_allows_refresh(self):
        module = WebViewProfileTests._load_app_module()
        app = module.WebViewApp.__new__(module.WebViewApp)
        app.logged_out = False
        app.live_id = ''
        module.core.client = object()
        module.core.login_token = 'test-token'
        module.core.set_current_user_api_url = 'https://example.test/set-current-user'
        module.core.get_page_display_api_url = 'https://example.test/get-page-display'
        with patch.object(module, 'request_live_page', return_value={
            'status': 'success', 'live_id': 'one',
        }) as request, patch.object(module, 'get_page_display_settings', side_effect=httpx.ConnectError('offline')):
            with self.assertRaisesRegex(RuntimeError, '操作已保存.*刷新状态或列表失败.*请刷新列表'):
                app.action('statistics', 'default', {'values': {'live_id': 'one'}})
        request.assert_called_once()


if __name__ == '__main__':
    unittest.main()
