"""Helpers for reading the pool list and selecting the local input pool."""

from flight_session import auth_headers


def _authorization_headers(login_token):
    return auth_headers(login_token)


def _normalize_pool_settings(data):
    if not isinstance(data, dict):
        raise ValueError("服务器返回的直播页卡池设置格式不正确")

    pool_name_list = data.get("pool_name_list")
    if (
        not isinstance(pool_name_list, list)
        or not pool_name_list
        or any(not isinstance(name, str) or not name.strip() for name in pool_name_list)
        or len(pool_name_list) != len(set(pool_name_list))
    ):
        raise ValueError("服务器返回的直播页卡池列表无效")
    return {
        "pool_name_list": tuple(pool_name_list),
    }


def get_page_pool_settings(http_client, url, login_token):
    response = http_client.get(
        url,
        headers=_authorization_headers(login_token),
    )
    response.raise_for_status()
    return _normalize_pool_settings(response.json())


def select_initial_pool_name(configured_pool_name, pool_name_list):
    if not pool_name_list:
        raise ValueError("直播页卡池列表不能为空")
    if configured_pool_name in pool_name_list:
        return configured_pool_name
    return pool_name_list[0]


def get_pool_selection_message(
    configured_pool_name,
    selected_pool_name,
    pool_name_list,
):
    if configured_pool_name not in pool_name_list:
        if configured_pool_name:
            prefix = f"配置文件中的卡池“{configured_pool_name}”已不可用"
        else:
            prefix = "配置文件中的卡池为空"
        return (
            f"{prefix}，保存后将改为“{selected_pool_name}”。"
        )
    return ""
