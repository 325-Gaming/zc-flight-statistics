from dataclasses import dataclass

from flight_session import auth_headers


@dataclass(frozen=True)
class GachaHistoryRecord:
    record_id: int
    event_name: str
    nickname: str
    sequence_no: int
    count: int
    character_list: tuple[str, ...]
    created_at: str
    is_revoked: bool
    request_id: str | None

    @classmethod
    def from_payload(cls, payload):
        character_list = payload.get("character_list")
        if not isinstance(character_list, list) or any(
            not isinstance(character, str) for character in character_list
        ):
            raise ValueError("历史记录中的抽卡结果无效")
        return cls(
            record_id=int(payload["record_id"]),
            event_name=str(payload["event_name"]),
            nickname=str(payload["nickname"]),
            sequence_no=int(payload["sequence_no"]),
            count=int(payload["count"]),
            character_list=tuple(character_list),
            created_at=str(payload["created_at"]),
            is_revoked=bool(payload["is_revoked"]),
            request_id=(
                str(payload["request_id"])
                if payload.get("request_id") is not None
                else None
            ),
        )


def sort_gacha_history_records(records):
    passenger_first_record_ids = {}
    for record in records:
        first_record_id = passenger_first_record_ids.get(record.nickname)
        if first_record_id is None or record.record_id < first_record_id:
            passenger_first_record_ids[record.nickname] = record.record_id
    return sorted(
        records,
        key=lambda record: (
            passenger_first_record_ids[record.nickname],
            record.sequence_no,
        ),
    )


def format_gacha_position(position, count):
    if count == 10:
        return f"{position}~{position + 9}"
    return str(position)


def get_gacha_history(
    client,
    url,
    login_token,
    event_name,
    nickname=None,
):
    params = {"event_name": event_name}
    if nickname:
        params["nickname"] = nickname
    response = client.get(
        url,
        headers=auth_headers(login_token),
        params=params,
    )
    response.raise_for_status()
    try:
        payload = response.json()
        records = payload["records"]
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("服务器返回的抽卡历史格式无效") from error
    if not isinstance(records, list):
        raise ValueError("服务器返回的抽卡历史格式无效")
    return sort_gacha_history_records(
        [GachaHistoryRecord.from_payload(record) for record in records]
    )
