import json
import os
import pathlib
import tempfile
import time
import unittest
from unittest.mock import patch

import httpx

from flight_session import (
    SessionCredentials,
    auth_headers,
    clear_session,
    get_login_info,
    has_flight_permission,
    load_session,
    logout,
    save_session,
)
from page_pool_settings import get_page_pool_settings


class FlightSessionTests(unittest.TestCase):
    def test_session_file_is_private_and_expires(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = pathlib.Path(temporary) / 'private' / 'session.json'
            save_session('12345', 'secret', path=path)
            self.assertEqual(load_session(path=path).token, 'secret')
            if os.name != 'nt':
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
            data = json.loads(path.read_text())
            data['saved_at'] = time.time() - 8 * 24 * 60 * 60
            path.write_text(json.dumps(data))
            self.assertIsNone(load_session(path=path))
            clear_session(path=path)
            self.assertFalse(path.exists())

    def test_missing_permission_clears_previous_result(self):
        self.assertTrue(has_flight_permission({
            'status': 'success', 'permission_code_list': ['zc.flight_user'],
        }))
        self.assertFalse(has_flight_permission({'status': 'success'}))
        self.assertFalse(has_flight_permission({
            'status': 'success', 'permission_code_list': [],
        }))

    def test_request_headers_and_logout_protocol(self):
        session = SessionCredentials('12345', 'secret', time.time())
        self.assertEqual(auth_headers(session), {
            'Authorization': 'Bearer secret', 'X-Zc-Flight-Identifier': '12345',
        })
        seen = []
        def handler(request):
            seen.append((request.url.path, request.read()))
            return httpx.Response(200, json={'status': 'success',
                                              'permission_code_list': ['zc.flight_user']})
        with tempfile.TemporaryDirectory() as temporary:
            with httpx.Client(transport=httpx.MockTransport(handler)) as client:
                with patch('flight_session.LOGIN_INFO_URL', 'https://example.test/api/kusa/get-login-info'), \
                     patch('flight_session.LOGOUT_URL', 'https://example.test/api/kusa/logout'), \
                     patch('flight_session.session_path', return_value=pathlib.Path(temporary) / 'session.json'):
                    save_session(session.identifier, session.token)
                    self.assertTrue(has_flight_permission(get_login_info(session, client=client)))
                    logout(session, client=client)
                    self.assertIsNone(load_session())
        self.assertEqual([item[0] for item in seen], [
            '/api/kusa/get-login-info', '/api/kusa/logout',
        ])
        self.assertTrue(all(json.loads(item[1]) == {
            'identifier': '12345', 'login_token': 'secret',
        } for item in seen))

    def test_protected_request_sends_identifier_and_session(self):
        session = SessionCredentials('12345', 'secret', time.time())
        def handler(request):
            self.assertEqual(request.headers['authorization'], 'Bearer secret')
            self.assertEqual(request.headers['x-zc-flight-identifier'], '12345')
            return httpx.Response(200, json={
                'current_pool_name': 'pool', 'pool_name_list': ['pool'],
            })
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            self.assertEqual(get_page_pool_settings(client, 'https://example.test/pool', session)[
                'current_pool_name'], 'pool')

    def test_logout_network_failure_still_clears_local_session(self):
        session = SessionCredentials('12345', 'secret', time.time())
        with tempfile.TemporaryDirectory() as temporary:
            path = pathlib.Path(temporary) / 'session.json'
            with httpx.Client(transport=httpx.MockTransport(
                lambda _request: httpx.Response(503))) as client:
                with patch('flight_session.LOGOUT_URL', 'https://example.test/logout'), \
                     patch('flight_session.session_path', return_value=path):
                    save_session(session.identifier, session.token)
                    with self.assertRaises(httpx.HTTPStatusError):
                        logout(session, client=client)
                    self.assertFalse(path.exists())
