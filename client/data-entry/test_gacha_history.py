import unittest

import httpx

from gacha_history import (
    GachaHistoryRecord,
    format_gacha_position,
    get_gacha_history,
    sort_gacha_history_records,
)


class GachaHistoryTests(unittest.TestCase):
    def test_formats_single_and_ten_pull_positions(self):
        self.assertEqual(format_gacha_position(1, 1), "1")
        self.assertEqual(format_gacha_position(1, 10), "1~10")
        self.assertEqual(format_gacha_position(11, 10), "11~20")

    def test_sorts_passengers_by_first_record_id_and_records_by_sequence(self):
        def record(record_id, nickname, sequence_no):
            return GachaHistoryRecord(
                record_id=record_id,
                event_name="event",
                nickname=nickname,
                sequence_no=sequence_no,
                count=1,
                character_list=("干员",),
                created_at="2026-09-13T12:00:00",
                is_revoked=False,
                request_id=None,
            )

        records = [
            record(20, "后到乘客", 1),
            record(12, "先到乘客", 2),
            record(10, "先到乘客", 1),
            record(21, "后到乘客", 2),
        ]

        sorted_records = sort_gacha_history_records(records)

        self.assertEqual(
            [item.record_id for item in sorted_records],
            [10, 12, 20, 21],
        )

    def test_requests_current_passenger_filter(self):
        requested_params = []

        def handler(request):
            requested_params.append(dict(request.url.params))
            return httpx.Response(
                200,
                json={
                    "records": [
                        {
                            "record_id": 7,
                            "event_name": "event",
                            "nickname": "user",
                            "sequence_no": 3,
                            "count": 1,
                            "character_list": ["六星干员"],
                            "created_at": "2026-09-11T12:00:00",
                            "is_revoked": False,
                            "request_id": None,
                        }
                    ]
                },
            )

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            records = get_gacha_history(
                client,
                "https://example.test/history",
                "token",
                "event",
                nickname="user",
            )

        self.assertEqual(requested_params, [{"event_name": "event", "nickname": "user"}])
        self.assertEqual(records[0].record_id, 7)
        self.assertEqual(records[0].sequence_no, 3)
        self.assertEqual(records[0].character_list, ("六星干员",))

    def test_omits_nickname_only_for_all_passengers(self):
        requested_params = []

        def handler(request):
            requested_params.append(dict(request.url.params))
            return httpx.Response(200, json={"records": []})

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            get_gacha_history(
                client,
                "https://example.test/history",
                "token",
                "event",
            )

        self.assertEqual(requested_params, [{"event_name": "event"}])

    def test_rejects_invalid_response(self):
        with httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={"records": {}})
            )
        ) as client:
            with self.assertRaisesRegex(ValueError, "历史格式无效"):
                get_gacha_history(
                    client,
                    "https://example.test/history",
                    "token",
                    "event",
                )


if __name__ == "__main__":
    unittest.main()
