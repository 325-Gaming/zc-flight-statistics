"""Helpers for reading and updating live-page display settings."""

import httpx


PAGE_DISPLAY_ITEMS = (
    ("is_scoreboard_visible", "左上角记分板"),
    ("is_bottom_info_visible", "底部信息栏（总开关）"),
    ("is_bottom_info_left_visible", "底部信息栏（左）"),
    ("is_bottom_info_right_visible", "底部信息栏（右）"),
    ("is_bottom_ticker_visible", "底部滚动条"),
)


def _authorization_headers(login_token):
    return {"Authorization": f"Bearer {login_token}"}


def _normalize_settings(data):
    if not isinstance(data, dict):
        raise ValueError("服务器返回的直播页面设置格式不正确")

    settings = {}
    for key, _ in PAGE_DISPLAY_ITEMS:
        value = data.get(key)
        if isinstance(value, bool):
            settings[key] = value
        elif value in (0, 1):
            settings[key] = bool(value)
        else:
            raise ValueError(f"服务器返回的直播页面设置缺少或包含无效字段：{key}")
    return settings


def get_page_display_settings(http_client, url, login_token):
    response = http_client.get(
        url,
        headers=_authorization_headers(login_token),
    )
    response.raise_for_status()
    return _normalize_settings(response.json())


def set_page_display_settings(http_client, url, login_token, settings):
    payload = _normalize_settings(settings)
    response = http_client.post(
        url,
        headers=_authorization_headers(login_token),
        json=payload,
    )
    response.raise_for_status()
    return _normalize_settings(response.json())
