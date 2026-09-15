import json
import unittest

import httpx

from page_display_settings import (
    PAGE_DISPLAY_ITEMS,
    get_page_display_settings,
    set_page_display_settings,
)


class PageDisplaySettingsTests(unittest.TestCase):
    def setUp(self):
        self.settings = {
            key: index % 2 == 0
            for index, (key, _) in enumerate(PAGE_DISPLAY_ITEMS)
        }
        self.settings["poll_interval_seconds"] = 5
        self.settings["page_style"] = "sunset"

    def test_get_page_display_settings(self):
        def handler(request):
            self.assertEqual(request.method, "GET")
            self.assertEqual(request.headers["authorization"], "Bearer test-token")
            return httpx.Response(200, json=self.settings)

        with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
            result = get_page_display_settings(
                http_client,
                "https://example.test/get-page-display",
                "test-token",
            )

        self.assertEqual(result, self.settings)

    def test_set_page_display_settings_submits_all_fields(self):
        def handler(request):
            self.assertEqual(request.method, "POST")
            self.assertEqual(request.headers["authorization"], "Bearer test-token")
            self.assertEqual(json.loads(request.content), self.settings)
            return httpx.Response(200, json={"status": "success", **self.settings})

        with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
            result = set_page_display_settings(
                http_client,
                "https://example.test/set-page-display",
                "test-token",
                self.settings,
            )

        self.assertEqual(result, self.settings)

    def test_get_page_display_settings_rejects_missing_fields(self):
        with httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={})
            )
        ) as http_client:
            with self.assertRaisesRegex(ValueError, "缺少或包含无效字段"):
                get_page_display_settings(
                    http_client,
                    "https://example.test/get-page-display",
                    "test-token",
                )

    def test_get_page_display_settings_rejects_missing_page_style(self):
        settings = dict(self.settings)
        del settings["page_style"]
        with httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=settings)
            )
        ) as http_client:
            with self.assertRaisesRegex(ValueError, "样式名称无效"):
                get_page_display_settings(
                    http_client,
                    "https://example.test/get-page-display",
                    "test-token",
                )

    def test_get_page_display_settings_rejects_invalid_poll_interval(self):
        for value in (True, 0, 61, "5"):
            with self.subTest(value=value):
                settings = dict(self.settings)
                settings["poll_interval_seconds"] = value
                with httpx.Client(
                    transport=httpx.MockTransport(
                        lambda request: httpx.Response(200, json=settings)
                    )
                ) as http_client:
                    with self.assertRaisesRegex(ValueError, "轮询间隔无效"):
                        get_page_display_settings(
                            http_client,
                            "https://example.test/get-page-display",
                            "test-token",
                        )


if __name__ == "__main__":
    unittest.main()
