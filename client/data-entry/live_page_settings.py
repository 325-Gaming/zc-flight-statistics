"""Authenticated management of live configurations through the existing API origin."""

from urllib.parse import urljoin

from flight_session import auth_headers


def request_live_page(http_client, current_user_url, login_token, action, *, live_id="", payload=None):
    # The configured passenger URL owns the origin and any proxy prefix.
    path = {
        "get-activity-list": "../activity/get-list",
        "get-live-list": "../live/get-list",
        "create-live": "../live/create",
        "set-live": "../live/set",
        "set-live-editor": "../live/set-editor",
        "remove-live": "../live/remove",
        "set-default-live": "../live/set-default",
    }[action]
    url = urljoin(current_user_url, path)
    kwargs = {"headers": auth_headers(login_token)}
    if live_id:
        kwargs["params"] = {"live_id": live_id}
    if payload is None:
        response = http_client.get(url, **kwargs)
    else:
        response = http_client.post(url, json=payload, **kwargs)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("服务器返回的直播配置格式不正确")
    if action == "get-live-list":
        if (
            not isinstance(data.get("live_list"), list)
            or not isinstance(data.get("operator_id"), int)
            or isinstance(data.get("operator_id"), bool)
            or not isinstance(data.get("is_admin"), bool)
            or not isinstance(data.get("default_live_id"), str)
        ):
            raise ValueError("服务器返回的直播配置列表格式不正确")
        for row in data["live_list"]:
            if (
                not isinstance(row, dict)
                or not all(isinstance(row.get(key), str) for key in ("live_id", "name", "activity_id", "event_name", "pool_name"))
                or not all(isinstance(row.get(key), int) and not isinstance(row.get(key), bool) and row[key] > 0 for key in ("owner_id", "follow_operator_id"))
                or not isinstance(row.get("is_enabled"), bool)
                or not isinstance(row.get("editor_id_list"), list)
                or any(not isinstance(value, int) or isinstance(value, bool) or value <= 0 for value in row["editor_id_list"])
                or (row.get("fixed_nickname") is not None and not isinstance(row["fixed_nickname"], str))
            ):
                raise ValueError("服务器返回的直播配置列表项目无效")
    elif action == "get-activity-list":
        if data.get("status") != "success" or not isinstance(data.get("activity_list"), list):
            raise ValueError("服务器返回的航空活动列表格式不正确")
        for row in data["activity_list"]:
            if (
                not isinstance(row, dict)
                or not all(isinstance(row.get(key), str) and row[key] for key in ("activity_id", "name", "role"))
                or row["role"] not in {"captain", "crew"}
            ):
                raise ValueError("服务器返回的航空活动列表项目无效")
    return data
