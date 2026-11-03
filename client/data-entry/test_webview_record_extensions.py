"""Exercise role, gift numbering and server-backed passenger state without live services."""

import json
import threading
import unittest
from unittest.mock import Mock, patch

import httpx

from gacha_history import GachaHistoryRecord
from gacha_upload import GachaUploadQueue, GachaUploadTask
import test_webview_profile as profile_tests


class RecordExtensionsTests(unittest.TestCase):
    def setUp(self):
        self.module = profile_tests.WebViewProfileTests._load_app_module()
        self.app = self.module.WebViewApp.__new__(self.module.WebViewApp)
        for name, value in {
            'lock': threading.RLock(), 'user_name_list': ['甲', '乙'], 'user_id': 0,
            'nickname': '甲', 'last_synced_user': '甲', 'gacha_index': 301,
            'passenger_state': {'甲': {'pulls': 300, 'has_gift': False}},
            'pending_uploads': {}, 'gift_operator': '限定', 'result': '', 'status': '',
            'captain_profile': None, 'page_is_active': False,
            'activity_list': [{'activity_id': 'activity', 'role': 'crew'}],
        }.items():
            setattr(self.app, name, value)
        core = self.module.core
        core.activity_id, core.pool_name, core.event_name = 'activity', 'pool', '活动'
        core.config = {}
        for key in self.module.HOTKEY_KEYS:
            setattr(core, key, '')
        self.app._emit_main = Mock()
        self.app.upload_queue = Mock()
        self.app.upload_queue.submit.side_effect = lambda **data: GachaUploadTask(**data, request_id=str(len(self.app.pending_uploads)))

    def test_ten_pull_range_and_gift_do_not_increment_pull_position(self):
        self.app.enqueue_gacha_result(10, ['三星干员'] * 10)
        self.assertEqual(self.app.status, '甲：第 301-310 抽已加入上传队列')
        self.app.enqueue_gacha_result(0, ['限定'], is_gift=True)
        self.assertEqual(self.app.gacha_index, 311)
        self.assertEqual(self.app.status, '甲：赠送记录已加入上传队列')
        self.assertTrue(self.app.pending_uploads['1'].is_gift)

    def test_role_follows_selected_activity_and_pending_scope(self):
        self.assertEqual(self.app._main_state()['role_label'], '乘务员')
        self.app.activity_list[0]['role'] = 'captain'
        self.assertEqual(self.app._main_state()['role_label'], '机长')
        self.app.pending_uploads['old'] = GachaUploadTask('old', 'pool', '乙', 10, 1, (), 'old')
        self.assertEqual(self.app._main_state()['pending_passengers'], [])

    def test_passenger_switch_keeps_server_pulls_and_queued_pulls(self):
        self.app.enqueue_gacha_result(10, ['三星干员'] * 10)
        self.module.core.request_set_current_user = Mock(return_value=True)
        self.app._current_user(1)
        self.assertEqual(self.app.gacha_index, 1)
        self.app._current_user(0)
        self.assertEqual(self.app.gacha_index, 311)

    def test_history_gift_occupies_record_sequence_but_not_actual_pulls(self):
        self.app.history_filter, self.app.history_nickname = 'current', None
        self.app.history_pending, self.app.history_status = False, ''
        records = [GachaHistoryRecord(i, '活动-pool', 'activity', '10001', 'pool', '甲', i,
            count, tuple(names), '2026-11-01T12:00:00', False, None, gift)
            for i, count, names, gift in [(1, 10, ['三星干员']*10, False), (2, 0, ['限定'], True), (3, 1, ['三星干员'], False)]]
        self.module.core.client, self.module.core.gacha_history_api_url, self.module.core.login_token = object(), 'test', 'token'
        self.app._refresh_passengers = Mock()
        with patch.object(self.module, 'get_gacha_history', return_value=records):
            rows = self.app._history_state()['rows']
        self.assertEqual([row['sequence'] for row in rows], [1, 2, 3])
        self.assertEqual([row['position'] for row in rows], ['1~10', '—', '11'])
        self.assertTrue(rows[1]['is_gift'])

    def test_gift_queue_payload_keeps_zero_pulls(self):
        requests = []
        with httpx.Client(transport=httpx.MockTransport(lambda request: requests.append(json.loads(request.content)) or httpx.Response(200))) as client:
            queue = GachaUploadQueue(client, 'https://example.test/submit', 'token')
            queue.submit('activity', 'pool', '甲', 0, 301, ['限定'], is_gift=True)
            queue.close()
        self.assertEqual(requests[0]['count'], 0)
        self.assertTrue(requests[0]['is_gift'])

    def test_gift_action_allows_below_300_but_rejects_existing_gift(self):
        self.app.logged_out = False
        self.app._refresh_passengers = Mock()
        self.app.passenger_state['甲']['pulls'] = 20
        self.app.gacha_index = 21
        self.app.action('main', 'gift', {})
        self.assertEqual(self.app.gacha_index, 21)
        self.assertTrue(self.app.pending_uploads['0'].is_gift)
        self.app.pending_uploads.clear()
        self.app.passenger_state['甲']['has_gift'] = True
        with self.assertRaisesRegex(ValueError, '已经领取'):
            self.app.action('main', 'gift', {})
