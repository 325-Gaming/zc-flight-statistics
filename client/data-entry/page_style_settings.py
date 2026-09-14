"""Helpers for reading and updating the live-page style."""

import re


PAGE_STYLE_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
DEFAULT_PAGE_STYLE = "classic"


def normalize_page_style_name(value):
    if (
        not isinstance(value, str)
        or PAGE_STYLE_NAME_PATTERN.fullmatch(value) is None
    ):
        raise ValueError("服务器返回的直播页面样式名称无效")
    return value


def select_available_page_style(current_page_style, available_page_styles):
    current_page_style = normalize_page_style_name(current_page_style)
    if current_page_style in available_page_styles:
        return current_page_style
    return DEFAULT_PAGE_STYLE


def get_available_page_styles(http_client, url):
    response = http_client.get(url)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict) or not isinstance(data.get("page_styles"), list):
        raise ValueError("服务器返回的直播页面样式列表格式不正确")

    page_styles = []
    for value in data["page_styles"]:
        page_style = normalize_page_style_name(value)
        if page_style not in page_styles:
            page_styles.append(page_style)
    if DEFAULT_PAGE_STYLE not in page_styles:
        page_styles.insert(0, DEFAULT_PAGE_STYLE)
    return tuple(page_styles)
