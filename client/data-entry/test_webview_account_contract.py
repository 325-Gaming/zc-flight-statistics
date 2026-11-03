"""Exercise the account bridge and form handlers without Node or live services."""

import ctypes
import ctypes.util
import pathlib
import sys
import unittest
from unittest.mock import Mock, patch

import test_webview_profile as profile_tests


class AccountBridgeTests(unittest.TestCase):
    def test_statistics_bridge_preserves_qq_strings(self):
        module = profile_tests.WebViewProfileTests._load_app_module()
        app = module.WebViewApp.__new__(module.WebViewApp)
        app.logged_out = False
        app.live_id = 'live'
        app._statistics_state = Mock(return_value={'user_id': '9007199254740993'})
        module.core.client = object()
        module.core.login_token = 'test-token'
        module.core.set_current_user_api_url = 'https://example.test/api/zc-flight/gachalog/set-current-user'
        for action, values in (
            ('create', {'follow_user_id': '9007199254740993'}),
            ('save', {'follow_user_id': '10002'}),
            ('editors', {'editor_user_id_list': ['9007199254740993', '10002']}),
        ):
            with patch.object(module, 'request_live_page', return_value={'live_id': 'live'}) as request:
                app.action('statistics', action, {'live_id': 'live', 'values': values})
                self.assertEqual(request.call_args.kwargs['payload'], values)
                self.assertEqual(request.call_args.kwargs['live_id'], 'live')


@unittest.skipUnless(sys.platform == 'darwin', 'Uses the macOS system JavaScriptCore framework')
class StatisticsFormTests(unittest.TestCase):
    def test_form_handlers_use_qq_strings_and_enforce_ui_roles(self):
        library = ctypes.CDLL(ctypes.util.find_library('JavaScriptCore'))
        pointer = ctypes.c_void_p
        signatures = {
            'JSGlobalContextCreate': ([pointer], pointer),
            'JSGlobalContextRelease': ([pointer], None),
            'JSStringCreateWithUTF8CString': ([ctypes.c_char_p], pointer),
            'JSStringRelease': ([pointer], None),
            'JSEvaluateScript': ([pointer, pointer, pointer, pointer, ctypes.c_int, ctypes.POINTER(pointer)], pointer),
            'JSValueToStringCopy': ([pointer, pointer, ctypes.POINTER(pointer)], pointer),
            'JSStringGetMaximumUTF8CStringSize': ([pointer], ctypes.c_size_t),
            'JSStringGetUTF8CString': ([pointer, ctypes.c_void_p, ctypes.c_size_t], ctypes.c_size_t),
        }
        for name, (arguments, result_type) in signatures.items():
            function = getattr(library, name)
            function.argtypes, function.restype = arguments, result_type
        context = library.JSGlobalContextCreate(None)
        self.addCleanup(library.JSGlobalContextRelease, context)

        def evaluate(source):
            script = library.JSStringCreateWithUTF8CString(source.encode())
            exception = pointer()
            try:
                value = library.JSEvaluateScript(context, script, None, None, 1, ctypes.byref(exception))
            finally:
                library.JSStringRelease(script)
            string = library.JSValueToStringCopy(context, exception.value or value, None)
            try:
                size = library.JSStringGetMaximumUTF8CStringSize(string)
                buffer = ctypes.create_string_buffer(size)
                library.JSStringGetUTF8CString(string, buffer, size)
                result = buffer.value.decode()
            finally:
                library.JSStringRelease(string)
            if exception.value:
                self.fail(result)
            return result

        evaluate('''
            var elements = {};
            var document = {
              getElementById(id) {
                return elements[id] ||= {value: '', disabled: false, checked: false,
                  reportValidity() { return /^[0-9]{5,16}$/.test(elements['live-follow'].value); }};
              }, addEventListener() {}
            };
            var window = {addEventListener() {}};
            var URL = class {
              constructor(value) { this.href = value; this.searchParams = {set() {}, delete() {}}; }
            };
        ''')
        evaluate((pathlib.Path(__file__).parent / 'webview_ui/app.js').read_text())
        evaluate('''
            var result = null, calls = [], dialogs = [];
            api = async (action, payload) => { calls.push({action, payload}); return {failed: true}; };
            showDialog = async (...args) => { dialogs.push(args); return true; };
            var check = (condition, message) => { if (!condition) throw Error(message); };
            state = {user_id: '9007199254740993', is_admin: false, default_live_id: '',
              live_id: 'live', url: 'https://example.test/live', event_name: '活动',
              activity_id: 'activity', pool_name: '卡池', pool_names: ['卡池'],
              activity_list: [{activity_id: 'activity', name: '活动', role: 'crew'}],
              live_list: [{live_id: 'live', name: '直播', activity_id: 'activity',
                event_name: '活动', pool_name: '卡池', owner_user_id: '9007199254740993',
                follow_user_id: '10002', editor_user_id_list: [], is_enabled: true}]};
            (async () => {
              renderStatistics();
              check(appElement.innerHTML.includes('你的QQ号：9007199254740993'), 'QQ label');
              check(!appElement.innerHTML.includes('账号编号'), 'internal account label');
              check(!elements['live-save'].disabled && !elements['live-grant'].disabled, 'owner controls');
              await elements['live-create'].onclick();
              check(calls[0].payload.values.follow_user_id === '10002', 'create uses string QQ');
              elements['live-follow'].value = '9007199254740993';
              await elements['live-save'].onclick();
              check(calls[1].payload.values.follow_user_id === '9007199254740993', 'QQ precision');
              elements['live-editors'].value = '10002, 9007199254740993';
              await elements['live-grant'].onclick();
              check(JSON.stringify(calls[2].payload.values.editor_user_id_list) ===
                '["10002","9007199254740993"]', 'editor strings');
              elements['live-editors'].value = '';
              await elements['live-grant'].onclick();
              check(calls[3].payload.values.editor_user_id_list.length === 0, 'clear grants');
              for (const invalid of ['1', '10002,2', '2@example.test', '1e10']) {
                elements['live-editors'].value = invalid;
                await elements['live-grant'].onclick();
              }
              check(calls.length === 4 && dialogs.length === 4, 'invalid QQ not submitted');
              elements['live-follow'].value = '1';
              await elements['live-save'].onclick();
              check(calls.length === 4, 'invalid follow not submitted');
              state.live_list[0].owner_user_id = '10002';
              state.live_list[0].editor_user_id_list = [state.user_id];
              renderStatistics();
              check(!elements['live-save'].disabled && elements['live-grant'].disabled,
                'editor cannot delegate');
              state.live_list[0].editor_user_id_list = [];
              state.activity_list[0].role = 'captain';
              renderStatistics();
              check(elements['live-save'].disabled && !elements['live-remove'].disabled,
                'captain removal does not imply edit access');
              result = 'ok';
            })().catch(error => { result = String(error); });
        ''')
        self.assertEqual(evaluate('result'), 'ok')


if __name__ == '__main__':
    unittest.main()
