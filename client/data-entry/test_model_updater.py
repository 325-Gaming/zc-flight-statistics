import hashlib
import json
import pathlib
import sys
import tempfile
import unittest

import httpx


DATA_ENTRY_DIR = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(DATA_ENTRY_DIR))

from model_updater import (  # noqa: E402
    MEBIBYTE,
    _format_download_complete,
    _format_download_status,
    update_models,
)


class ModelUpdaterTests(unittest.TestCase):
    def test_formats_download_status(self):
        status = _format_download_status(
            "gacha10",
            10 * MEBIBYTE,
            32 * MEBIBYTE,
            2 * MEBIBYTE,
            16,
            5,
        )

        self.assertEqual(
            status,
            "下载 gacha10           10.00/32.00 MiB   31.2%     2.00 MiB/s  "
            "剩余 00:11",
        )

    def test_formats_download_complete(self):
        status = _format_download_complete(
            "gacha10.keras",
            32 * MEBIBYTE,
            10,
            16,
            5,
        )

        self.assertEqual(
            status,
            "完成 gacha10.keras     32.00 MiB  用时 00:10  平均    3.20 MiB/s",
        )

    def _client(self, files, versions=None, corrupt_download=False):
        versions = versions or {name: "2026.09.02.1" for name in files}

        def handler(request):
            self.assertEqual(request.headers.get("authorization"), "Bearer test-token")
            if request.url.path.endswith("/manifest"):
                models = {}
                for name, content in files.items():
                    models[name] = {
                        "version": versions[name],
                        "sha256": hashlib.sha256(content).hexdigest(),
                        "size": len(content),
                        "url": f"/models/{name}",
                        "min_client_version": "0.2.0",
                    }
                return httpx.Response(
                    200, json={"schema_version": 1, "models": models}
                )
            name = request.url.path.rsplit("/", 1)[-1]
            content = b"corrupt" if corrupt_download else files[name]
            return httpx.Response(200, content=content)

        return httpx.Client(transport=httpx.MockTransport(handler))

    def test_downloads_missing_models_and_writes_manifest(self):
        files = {"image_type": b"image-model", "gacha10": b"gacha-model"}
        with tempfile.TemporaryDirectory() as temp_dir, self._client(files) as client:
            models_dir = pathlib.Path(temp_dir)
            results = update_models(
                "https://example.test/api/models/manifest",
                models_dir,
                "0.2.0",
                login_token="test-token",
                client=client,
            )

            self.assertEqual(results["image_type"].status, "downloaded")
            self.assertEqual((models_dir / "image_type.keras").read_bytes(), files["image_type"])
            manifest = json.loads((models_dir / "manifest.json").read_text("utf-8"))
            self.assertEqual(manifest["models"]["gacha10"]["version"], "2026.09.02.1")

    def test_matching_legacy_files_are_not_downloaded(self):
        files = {"image_type": b"image-model", "gacha10": b"gacha-model"}
        requests = []

        def handler(request):
            requests.append(request.url.path)
            models = {
                name: {
                    "version": "2026.09.02.1",
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "size": len(content),
                    "url": f"/models/{name}",
                }
                for name, content in files.items()
            }
            return httpx.Response(200, json={"schema_version": 1, "models": models})

        with tempfile.TemporaryDirectory() as temp_dir:
            models_dir = pathlib.Path(temp_dir)
            for name, filename in {"image_type": "image_type.keras", "gacha10": "gacha10.keras"}.items():
                (models_dir / filename).write_bytes(files[name])
            with httpx.Client(transport=httpx.MockTransport(handler)) as client:
                results = update_models(
                    "https://example.test/api/models/manifest",
                    models_dir,
                    "0.2.0",
                    client=client,
                )

            self.assertEqual(requests, ["/api/models/manifest"])
            self.assertTrue(all(result.status == "current" for result in results.values()))

    def test_bad_download_does_not_replace_existing_model(self):
        files = {"image_type": b"new-image", "gacha10": b"new-gacha"}
        with tempfile.TemporaryDirectory() as temp_dir, self._client(
            files, corrupt_download=True
        ) as client:
            models_dir = pathlib.Path(temp_dir)
            old_model = models_dir / "image_type.keras"
            old_model.write_bytes(b"old-image")

            with self.assertRaises(ValueError):
                update_models(
                    "https://example.test/api/models/manifest",
                    models_dir,
                    "0.2.0",
                    login_token="test-token",
                    client=client,
                )

            self.assertEqual(old_model.read_bytes(), b"old-image")


if __name__ == "__main__":
    unittest.main()
