"""Helpers for composing event names."""


def compose_event_name(event_name, pool_name):
    event_name = str(event_name).strip()
    pool_name = str(pool_name).strip()
    if not event_name:
        raise ValueError("活动名称不能为空")
    if not pool_name:
        raise ValueError("卡池名称不能为空")
    return f"{event_name}-{pool_name}"
