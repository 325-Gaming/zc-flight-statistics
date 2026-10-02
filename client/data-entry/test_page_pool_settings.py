import json
import unittest

import httpx

from page_pool_settings import (
    get_page_pool_settings,
    get_pool_sync_message,
    select_initial_pool_name,
    set_current_pool,
)


class PagePoolSettingsTests(unittest.TestCase):
    def test_initial_pool_prefers_available_configured_pool(self):
        self.assertEqual(
            select_initial_pool_name(
                "配置卡池",
                "服务端卡池",
                ("服务端卡池", "配置卡池"),
            ),
            "配置卡池",
        )

    def test_initial_pool_falls_back_to_current_pool(self):
        self.assertEqual(
            select_initial_pool_name(
                "失效卡池",
                "服务端卡池",
                ("服务端卡池", "其他卡池"),
            ),
            "服务端卡池",
        )

    def test_initial_pool_falls_back_to_first_available_pool(self):
        self.assertEqual(
            select_initial_pool_name(
                "失效卡池",
                "失效服务端卡池",
                ("第一个卡池", "其他卡池"),
            ),
            "第一个卡池",
        )

    def test_pool_sync_message_reports_server_difference(self):
        self.assertEqual(
            get_pool_sync_message(
                "配置卡池",
                "服务端卡池",
                "配置卡池",
                ("服务端卡池", "配置卡池"),
            ),
            "直播页当前卡池为“服务端卡池”，保存后将切换为“配置卡池”。",
        )

    def test_pool_sync_message_reports_unavailable_configured_pool(self):
        self.assertEqual(
            get_pool_sync_message(
                "失效卡池",
                "服务端卡池",
                "服务端卡池",
                ("服务端卡池", "其他卡池"),
            ),
            "配置文件中的卡池“失效卡池”已不可用，保存后将改为“服务端卡池”。",
        )

    def test_get_page_pool_settings_preserves_server_order(self):
        def handler(request):
            self.assertEqual(request.method, "GET")
            self.assertEqual(request.headers["authorization"], "Bearer test-token")
            return httpx.Response(
                200,
                json={
                    "current_pool_name": "当前卡池",
                    "pool_name_list": ["最新卡池", "当前卡池", "旧卡池"],
                },
            )

        with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
            result = get_page_pool_settings(
                http_client,
                "https://example.test/get-pool-list",
                "test-token",
            )

        self.assertEqual(result["current_pool_name"], "当前卡池")
        self.assertEqual(
            result["pool_name_list"],
            ("最新卡池", "当前卡池", "旧卡池"),
        )

    def test_set_current_pool(self):
        def handler(request):
            self.assertEqual(request.method, "POST")
            self.assertEqual(request.headers["authorization"], "Bearer test-token")
            self.assertEqual(json.loads(request.content), {"pool_name": "新卡池"})
            return httpx.Response(
                200,
                json={"status": "success", "current_pool_name": "新卡池"},
            )

        with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
            result = set_current_pool(
                http_client,
                "https://example.test/set-current-pool",
                "test-token",
                "新卡池",
            )

        self.assertEqual(result, "新卡池")

    def test_get_page_pool_settings_rejects_duplicate_names(self):
        with httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={
                        "current_pool_name": "卡池",
                        "pool_name_list": ["卡池", "卡池"],
                    },
                )
            )
        ) as http_client:
            with self.assertRaisesRegex(ValueError, "卡池列表无效"):
                get_page_pool_settings(
                    http_client,
                    "https://example.test/get-pool-list",
                    "test-token",
                )


if __name__ == "__main__":
    unittest.main()
