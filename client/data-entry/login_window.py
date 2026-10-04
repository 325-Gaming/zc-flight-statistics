"""Use the same personal-center page and login flow as yubo.run/user."""

import json
import os
import sys
import threading
import time

import httpx
import webview

from flight_session import (
    SessionCredentials,
    clear_session,
    get_login_info,
    has_flight_permission,
    load_session,
    save_session,
)


def ensure_login():
    saved = load_session()
    if saved:
        # Network failure leaves the saved credential intact for a later retry.
        if has_flight_permission(get_login_info(saved)):
            return
        clear_session()
    else:
        clear_session()

    window = webview.create_window(
        'Zc航空 · 羽bot个人中心登录',
        'https://yubo.run/user/', width=1000, height=750, min_size=(700, 550),
    )
    accepted = False
    closed = threading.Event()
    window.events.closed += lambda *_args: closed.set()

    def check_login():
        nonlocal accepted
        last_denied = None
        next_denied_check = 0
        while not accepted and not closed.is_set():
            try:
                raw = window.evaluate_js(
                    "JSON.stringify({identifier: localStorage.getItem('login_identifier'), "
                    "token: localStorage.getItem('login_token')})"
                )
                data = json.loads(raw) if isinstance(raw, str) else raw
                identifier, token = data.get('identifier'), data.get('token')
                candidate = (identifier, token)
                if identifier and token and (
                    candidate != last_denied or time.monotonic() >= next_denied_check
                ):
                    info = get_login_info(SessionCredentials(identifier, token, time.time()))
                    if has_flight_permission(info):
                        save_session(identifier, token)
                        accepted = True
                        window.destroy()
                        return
                    if info.get('status') == 'success':
                        if candidate != last_denied:
                            window.evaluate_js("alert('当前账号没有Zc航空数据录入权限，请联系管理员。')")
                        last_denied = candidate
                        next_denied_check = time.monotonic() + 30
            except (AttributeError, ValueError, TypeError, httpx.HTTPError):
                # The page may still be loading, or the network may be unavailable.
                pass
            closed.wait(2)

    webview.start(check_login, gui='edgechromium' if sys.platform == 'win32' else None,
                  private_mode=True)
    if not accepted:
        raise SystemExit(0)
    os.execv(sys.executable, [sys.executable, *sys.argv])
