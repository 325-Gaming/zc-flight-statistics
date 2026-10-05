"""Use the same personal-center page and login flow as yubo.run/user."""

import json
import os
import pathlib
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
    logout,
    save_session,
)


DENIED_PAGE_READY_SCRIPT = "document.readyState === 'complete' && location.origin === 'https://yubo.run'"
DENIED_PAGE_SCRIPT = """(() => {
  document.title = 'Zc航空数据录入 · 无权限';
  document.body.classList.remove('user-workspace');
  const main = document.createElement('main');
  Object.assign(main.style, {
    minHeight: '100vh', display: 'flex', flexDirection: 'column',
    alignItems: 'center', justifyContent: 'center', gap: '20px',
    padding: '24px', textAlign: 'center',
  });
  const message = document.createElement('p');
  message.textContent = '当前账号没有Zc航空数据录入权限，请联系管理员。';
  const button = document.createElement('button');
  button.className = 'el-button el-button--primary';
  button.type = 'button';
  button.textContent = '退出登录';
  button.onclick = async () => {
    button.disabled = true;
    try {
      if (await window.pywebview.api.logout()) return;
    } catch (_) {}
    message.textContent = '退出登录失败，请检查网络后重试。';
    button.disabled = false;
  };
  main.append(message, button);
  document.body.replaceChildren(main);
})()"""


class LoginBridge:
    def __init__(self):
        self.session = None
        self.window = None

    def logout(self):
        if self.session is None:
            return False
        try:
            result = logout(self.session)
            if result.get('message') != '退出登录成功':
                return False
        except (httpx.HTTPError, ValueError, TypeError):
            return False
        threading.Timer(0.2, self.window.destroy).start()
        return True


def ensure_login():
    saved = load_session()
    denied_session = None
    if saved:
        # Network failure leaves the saved credential intact for a later retry.
        info = get_login_info(saved)
        if has_flight_permission(info):
            return
        if isinstance(info, dict) and info.get('status') == 'success':
            denied_session = saved
        else:
            clear_session()
    else:
        clear_session()

    bridge = LoginBridge()
    window = webview.create_window(
        'Zc航空 · 羽bot个人中心登录',
        'https://yubo.run/user/', width=1000, height=750, min_size=(700, 550),
        js_api=bridge,
    )
    bridge.window = window
    accepted = False
    closed = threading.Event()
    window.events.closed += lambda *_args: closed.set()

    def check_login():
        nonlocal accepted
        while not accepted and not closed.is_set():
            try:
                if denied_session is not None:
                    if window.evaluate_js(DENIED_PAGE_READY_SCRIPT) is not True:
                        closed.wait(2)
                        continue
                    bridge.session = denied_session
                    window.evaluate_js(DENIED_PAGE_SCRIPT)
                    return
                raw = window.evaluate_js(
                    "JSON.stringify({identifier: localStorage.getItem('login_identifier'), "
                    "token: localStorage.getItem('login_token')})"
                )
                data = json.loads(raw) if isinstance(raw, str) else raw
                identifier, token = data.get('identifier'), data.get('token')
                if identifier and token:
                    session = SessionCredentials(identifier, token, time.time())
                    info = get_login_info(session)
                    if has_flight_permission(info):
                        save_session(identifier, token)
                        accepted = True
                        window.destroy()
                        return
                    if info.get('status') == 'success':
                        save_session(identifier, token)
                        bridge.session = session
                        window.evaluate_js(DENIED_PAGE_SCRIPT)
                        return
            except (AttributeError, ValueError, TypeError, httpx.HTTPError):
                # The page may still be loading, or the network may be unavailable.
                pass
            closed.wait(2)

    icon_name = 'favicon.png' if sys.platform == 'darwin' else 'favicon.ico'
    webview.start(
        check_login,
        gui='edgechromium' if sys.platform == 'win32' else None,
        private_mode=True,
        icon=str(pathlib.Path(__file__).resolve().parent / icon_name),
    )
    if not accepted:
        raise SystemExit(0)
    os.execv(sys.executable, [sys.executable, *sys.argv])
