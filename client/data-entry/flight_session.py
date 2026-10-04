"""Personal-center session storage and request helpers for the desktop client."""

import json
import os
import pathlib
import tempfile
import time
from dataclasses import dataclass

import httpx
from dotenv import dotenv_values


BASE_DIR = pathlib.Path(__file__).resolve().parent
SETTINGS = dotenv_values(BASE_DIR / '.env', interpolate=False)
LOGIN_INFO_URL = SETTINGS.get('ZCFLIGHT_LOGIN_INFO_URL') or 'https://yubo.run/api/kusa/get-login-info'
LOGOUT_URL = SETTINGS.get('ZCFLIGHT_LOGOUT_URL') or 'https://yubo.run/api/kusa/logout'
MAX_AGE_SECONDS = 7 * 24 * 60 * 60


@dataclass(frozen=True)
class SessionCredentials:
    identifier: str
    token: str
    saved_at: float


def session_path():
    if os.name == 'nt':
        root = pathlib.Path(os.environ['LOCALAPPDATA'])
    else:
        root = pathlib.Path.home() / '.config'
    return root / 'zc-flight-data-entry' / 'session.json'


def save_session(identifier, token, *, path=None):
    path = pathlib.Path(path or session_path())
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name != 'nt':
        path.parent.chmod(0o700)
    descriptor, temporary = tempfile.mkstemp(prefix='.session-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
            json.dump({'identifier': identifier, 'token': token, 'saved_at': time.time()}, output)
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_session(*, path=None):
    path = pathlib.Path(path or session_path())
    try:
        if os.name != 'nt' and path.stat().st_mode & 0o077:
            return None
        data = json.loads(path.read_text(encoding='utf-8'))
        session = SessionCredentials(data['identifier'], data['token'], data['saved_at'])
        if (not isinstance(session.identifier, str) or not session.identifier
                or not isinstance(session.token, str) or not session.token
                or not isinstance(session.saved_at, (int, float))
                or not 0 <= time.time() - session.saved_at < MAX_AGE_SECONDS):
            return None
        return session
    except (OSError, ValueError, KeyError, TypeError):
        return None


def clear_session(*, path=None):
    pathlib.Path(path or session_path()).unlink(missing_ok=True)


def auth_headers(session):
    if isinstance(session, SessionCredentials):
        return {'Authorization': f'Bearer {session.token}',
                'X-Zc-Flight-Identifier': session.identifier}
    # Library callers in existing offline tests pass a token string.
    return {'Authorization': f'Bearer {session}'}


def get_login_info(session, *, client=None):
    owned = client is None
    client = client or httpx.Client(timeout=15)
    try:
        response = client.post(LOGIN_INFO_URL, json={
            'identifier': session.identifier, 'login_token': session.token,
        })
        response.raise_for_status()
        return response.json()
    finally:
        if owned:
            client.close()


def has_flight_permission(data):
    return (isinstance(data, dict) and data.get('status') == 'success'
            and isinstance(data.get('permission_code_list', []), list)
            and 'zc.flight_user' in data.get('permission_code_list', []))


def logout(session, *, client=None):
    owned = client is None
    client = client or httpx.Client(timeout=15)
    try:
        response = client.post(LOGOUT_URL, json={
            'identifier': session.identifier, 'login_token': session.token,
        })
        response.raise_for_status()
        return response.json()
    finally:
        if owned:
            client.close()
        clear_session()
