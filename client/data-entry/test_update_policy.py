"""Validate the online data-entry minimum-version policy and startup gate."""

import json
import unittest
from unittest.mock import patch

import httpx

import app_updater


def _policy(**overrides):
    entry = {
        "schema_version": 1,
        "minimum_supported_version": "2.2.0",
        "message": "低于此版本的客户端需要更新后才能继续使用。",
    }
    entry.update(overrides)
    return json.dumps({"data-entry": entry}, ensure_ascii=False).encode("utf-8")


class _Response:
    def __init__(self, status=200, body=b"", headers=None, error=None):
        self.status_code = status
        self.headers = headers or {}
        self.body = body
        self.error = error

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def iter_bytes(self):
        if self.error:
            raise self.error
        yield self.body


class UpdatePolicyTests(unittest.TestCase):
    def test_valid_policy_and_strict_semantic_version(self):
        self.assertEqual(
            app_updater.validate_update_policy(_policy()),
            {
                "schema_version": 1,
                "minimum_supported_version": "2.2.0",
                "message": "低于此版本的客户端需要更新后才能继续使用。",
            },
        )

    def test_rejects_malformed_json_duplicate_and_unknown_schema(self):
        invalid = (
            b"{",
            b'{"data-entry":{"schema_version":1,"schema_version":1,'
            b'"minimum_supported_version":"2.2.0","message":"x"}}',
            _policy(schema_version=2),
            _policy(schema_version=True),
            b'{"data-entry":{}}',
            b'{"data-entry":{"schema_version":1,"minimum_supported_version":"2.2.0",'
            b'"message":"ok","extra":true}}',
            b"\xff",
        )
        for payload in invalid:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                app_updater.validate_update_policy(payload)

    def test_rejects_invalid_field_types_lengths_and_versions(self):
        for value in (None, 2.2, 22, "2.2", "02.2.0", "2.02.0", "2.2.0-rc1",
                      "v2.2.0", "2.2.0\n", "99999999999999999999999999999999999999999999999999999999999999999.0.0"):
            with self.subTest(version=value), self.assertRaises(ValueError):
                app_updater.validate_update_policy(_policy(minimum_supported_version=value))
        for value in (None, 1, [], "", " " * 5, "x" * 501, "line\nbreak\x01"):
            with self.subTest(message=value), self.assertRaises(ValueError):
                app_updater.validate_update_policy(_policy(message=value))
        with self.assertRaises(ValueError):
            app_updater.validate_update_policy(b"x" * (app_updater.MAX_POLICY_SIZE + 1))

    def test_fetches_only_fixed_official_url_and_rejects_http_error_and_oversize(self):
        response = _Response(body=_policy())
        with patch("httpx.stream", return_value=response) as request:
            self.assertEqual(app_updater.fetch_update_policy()["minimum_supported_version"], "2.2.0")
        self.assertEqual(request.call_args.args[:2], ("GET", app_updater.UPDATE_POLICY_URL))
        self.assertFalse(request.call_args.kwargs["follow_redirects"])

        cases = (
            (_Response(status=503), "HTTP 503"),
            (_Response(headers={"content-length": str(app_updater.MAX_POLICY_SIZE + 1)}), "大小限制"),
            (_Response(body=b"x" * (app_updater.MAX_POLICY_SIZE + 1)), "大小限制"),
            (_Response(body=b"not-json"), "不是有效的"),
            (_Response(error=httpx.ReadTimeout("read timeout")), "超时"),
            (_Response(error=httpx.ConnectTimeout("connect timeout")), "超时"),
        )
        for result, message in cases:
            with self.subTest(message=message), patch("httpx.stream", return_value=result):
                with self.assertRaisesRegex(ValueError, message):
                    app_updater.fetch_update_policy()
        with patch("httpx.stream", side_effect=httpx.ConnectError("connection failed")):
            with self.assertRaisesRegex(ValueError, "无法连接"):
                app_updater.fetch_update_policy()

    def test_validates_and_fetches_only_a_static_official_version(self):
        self.assertEqual(
            app_updater.validate_version_source(
                b'"""Application version information."""\n\n__version__ = "2.3.1"\n'
            ),
            "2.3.1",
        )
        invalid_sources = (
            b"__version__ = get_version()\n",
            b'__version__ = "2.3"\n',
            b'__version__ = "2.3.1"\n__version__ = "2.3.2"\n',
            b'__version__: str = "2.3.1"\n',
            b"if True:\n    __version__ = '2.3.1'\n",
            b"\xff",
            b"x" * (app_updater.MAX_VERSION_SOURCE_SIZE + 1),
        )
        for payload in invalid_sources:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                app_updater.validate_version_source(payload)

        response = _Response(body=b'__version__ = "2.4.0"\n')
        with patch("httpx.stream", return_value=response) as request:
            self.assertEqual(app_updater.fetch_official_version(), "2.4.0")
        self.assertEqual(request.call_args.args[:2], ("GET", app_updater.VERSION_SOURCE_URL))
        self.assertFalse(request.call_args.kwargs["follow_redirects"])
        self.assertEqual(request.call_args.kwargs["headers"], {"Accept": "text/plain"})

        for result, message in (
            (_Response(status=503), "HTTP 503"),
            (_Response(headers={"content-length": "bad"}), "Content-Length"),
            (_Response(headers={
                "content-length": str(app_updater.MAX_VERSION_SOURCE_SIZE + 1),
            }), "大小限制"),
            (_Response(error=httpx.ReadTimeout("read timeout")), "超时"),
        ):
            with self.subTest(message=message), patch("httpx.stream", return_value=result):
                with self.assertRaisesRegex(ValueError, message):
                    app_updater.fetch_official_version()

    def test_startup_enforces_only_minimum_and_keeps_regular_update_optional(self):
        with patch.object(app_updater, "_release_data", return_value=[
            self.release("2.1.9"),
            self.release("2.2.0"),
            self.release("2.4.0"),
        ]) as request:
            forced = app_updater.check_startup_update("2.1.9", "2.2.0")
            self.assertTrue(forced["required"])
            self.assertEqual(forced["offer"]["version"], "2.4.0")
            below_target = app_updater.check_startup_update("2.2.0", "2.2.0")
            current = app_updater.check_startup_update("2.4.0", "2.2.0")
        self.assertFalse(below_target["required"])
        self.assertFalse(below_target["offer"]["available"])
        self.assertFalse(current["required"])
        self.assertFalse(current["offer"]["available"])
        request.assert_called_once()

    def test_supported_startup_does_not_request_releases(self):
        with patch.object(app_updater, "_release_data") as request:
            result = app_updater.check_startup_update("2.4.0", "2.2.0")
        self.assertFalse(result["required"])
        self.assertFalse(result["offer"]["available"])
        request.assert_not_called()

    def test_higher_official_version_gates_optional_release_lookup(self):
        release = self.release("2.4.0")
        with patch.object(app_updater, "_release_data", return_value=[release]) as request:
            current = app_updater.check_startup_update(
                "2.3.1", "2.2.0", official_version="2.3.1",
            )
            older = app_updater.check_startup_update(
                "2.3.1", "2.2.0", official_version="2.3.0",
            )
            newer = app_updater.check_startup_update(
                "2.3.1", "2.2.0", official_version="2.3.2",
            )
        request.assert_called_once()
        self.assertFalse(current["offer"]["available"])
        self.assertFalse(older["offer"]["available"])
        self.assertFalse(newer["required"])
        self.assertTrue(newer["offer"]["available"])
        self.assertEqual(newer["offer"]["version"], "2.4.0")

    def test_optional_release_failure_does_not_block_supported_startup(self):
        with patch.object(
            app_updater, "_release_data",
            side_effect=ValueError("无法连接 GitHub Release 服务"),
        ) as request:
            result = app_updater.check_startup_update(
                "2.3.1", "2.2.0", official_version="2.3.2",
            )
        request.assert_called_once()
        self.assertFalse(result["required"])
        self.assertFalse(result["offer"]["available"])
        self.assertIn("无法连接 GitHub Release", result["check_error"])

    def test_forced_startup_keeps_gate_when_release_api_fails(self):
        with patch.object(
            app_updater, "_release_data",
            side_effect=ValueError("无法连接 GitHub Release 服务"),
        ):
            with self.assertRaisesRegex(ValueError, "无法连接 GitHub Release"):
                app_updater.check_startup_update("2.1.0", "2.2.0")

    def test_behind_policy_still_requires_release_even_with_old_version_hint(self):
        release = self.release("2.3.0")
        with patch.object(app_updater, "_release_data", return_value=[release]) as request:
            result = app_updater.check_startup_update(
                "2.1.0", "2.2.0", official_version="2.0.0",
            )
        request.assert_called_once()
        self.assertTrue(result["required"])
        self.assertEqual(result["offer"]["version"], "2.3.0")

    def test_forced_startup_requires_a_release_checksum(self):
        release = self.release("2.3.0", digest=None)
        release["assets"][0].pop("digest")
        with patch.object(app_updater, "_release_data", return_value=[release]):
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                app_updater.check_startup_update("2.1.0", "2.2.0")

    def test_force_repair_checks_release_even_when_version_is_supported(self):
        release = self.release("2.4.0")
        with patch.object(app_updater, "_release_data", return_value=[release]) as request:
            result = app_updater.check_startup_update(
                "2.4.0", "2.2.0", force_repair=True,
            )
        self.assertTrue(result["required"])
        self.assertEqual(result["offer"]["version"], "2.4.0")
        self.assertTrue(result["offer"]["force_dependencies"])
        request.assert_called_once()

    def test_startup_does_not_accept_prerelease_draft_missing_asset_or_bad_digest(self):
        releases = [
            self.release("2.3.0", draft=True),
            self.release("2.4.0", prerelease=True),
        ]
        with patch.object(app_updater, "_release_data", return_value=releases):
            with self.assertRaisesRegex(ValueError, "没有可验证的稳定版 Release"):
                app_updater.check_startup_update("2.1.0", "2.2.0")

        for release in (
            self.release("2.3.0", assets=[]),
            self.release("2.3.0", digest="invalid"),
        ):
            with self.subTest(release=release), patch.object(
                app_updater, "_release_data", return_value=[release],
            ):
                with self.assertRaises(ValueError):
                    app_updater.check_startup_update("2.1.0", "2.2.0")

    def test_broken_optional_asset_does_not_block_supported_client(self):
        release = self.release("2.3.0", assets=[])
        with patch.object(app_updater, "_release_data", return_value=[release]):
            result = app_updater.check_startup_update(
                "2.2.0", "2.2.0", official_version="2.3.0",
            )
        self.assertFalse(result["required"])
        self.assertFalse(result["offer"]["available"])

    @staticmethod
    def release(version, draft=False, prerelease=False, assets=None, digest="sha256:" + "a" * 64):
        tag = f"data-entry/v{version}"
        if assets is None:
            assets = [{
                "name": f"data-entry-v{version}.zip",
                "state": "uploaded",
                "size": 123,
                "digest": digest,
                "browser_download_url":
                    f"https://github.com/{app_updater.REPOSITORY}/releases/download/"
                    f"{tag.replace('/', '%2F')}/data-entry-v{version}.zip",
            }]
        return {
            "tag_name": tag,
            "draft": draft,
            "prerelease": prerelease,
            "assets": assets,
        }


if __name__ == "__main__":
    unittest.main()
