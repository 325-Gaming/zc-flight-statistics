"""Helpers for reading and updating live-page display settings."""

import httpx

from page_style_settings import normalize_page_style_name


PAGE_DISPLAY_ITEMS = (
    ("is_scoreboard_visible", "左上角记分板"),
    ("is_bottom_info_visible", "底部信息栏（总开关）"),
    ("is_bottom_info_left_visible", "底部信息栏（左）"),
    ("is_bottom_info_right_visible", "底部信息栏（右）"),
    ("is_bottom_ticker_visible", "底部滚动条"),
)
POLL_INTERVAL_MAX_SECONDS = 60
POLL_INTERVAL_MIN_SECONDS = 1


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
    poll_interval_seconds = data.get("poll_interval_seconds")
    if (
        isinstance(poll_interval_seconds, bool)
        or not isinstance(poll_interval_seconds, int)
        or not POLL_INTERVAL_MIN_SECONDS
        <= poll_interval_seconds
        <= POLL_INTERVAL_MAX_SECONDS
    ):
        raise ValueError("服务器返回的直播页面轮询间隔无效")
    settings["poll_interval_seconds"] = poll_interval_seconds
    settings["page_style"] = normalize_page_style_name(data.get("page_style"))
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
