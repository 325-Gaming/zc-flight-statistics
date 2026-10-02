import unittest

import httpx

from page_style_settings import (
    get_available_page_style_list,
    normalize_page_style_name,
    select_available_page_style,
)


class PageStyleSettingsTests(unittest.TestCase):
    def test_get_available_page_style_list_adds_default_and_removes_duplicates(self):
        def handler(request):
            self.assertEqual(request.method, "GET")
            self.assertNotIn("authorization", request.headers)
            return httpx.Response(
                200,
                json={"page_style_list": ["sunset", "sunset"]},
            )

        with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
            result = get_available_page_style_list(
                http_client,
                "https://example.test/get-page-style-list",
            )

        self.assertEqual(result, ("classic", "sunset"))

    def test_rejects_invalid_page_style_name(self):
        with httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={"page_style_list": ["../classic"]},
                )
            )
        ) as http_client:
            with self.assertRaisesRegex(ValueError, "样式名称无效"):
                get_available_page_style_list(
                    http_client,
                    "https://example.test/get-page-style-list",
                )

    def test_normalize_page_style_name(self):
        self.assertEqual(normalize_page_style_name("dark-blue_2"), "dark-blue_2")
        with self.assertRaisesRegex(ValueError, "样式名称无效"):
            normalize_page_style_name("../classic")

    def test_selects_current_page_style_when_available(self):
        self.assertEqual(
            select_available_page_style("sunset", ("classic", "sunset")),
            "sunset",
        )

    def test_falls_back_when_current_page_style_is_unavailable(self):
        self.assertEqual(
            select_available_page_style("removed", ("classic", "sunset")),
            "classic",
        )


if __name__ == "__main__":
    unittest.main()
