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
    def test_keras_cache_does_not_prevent_downloading_onnx(self):
        files = {
            "image_type": b"onnx-image-model",
            "gacha10": b"onnx-gacha-model",
            "operators": "能天使\n推进之王\n".encode(),
        }
        with tempfile.TemporaryDirectory() as temp_dir, self._client(files) as client:
            models_dir = pathlib.Path(temp_dir)
            old_models = {}
            for name in ("image_type", "gacha10"):
                (models_dir / f"{name}.keras").write_bytes(b"old-keras")
                old_models[name] = {
                    "version": "2099.01.01.1",
                    "sha256": hashlib.sha256(b"old-keras").hexdigest(),
                    "size": len(b"old-keras"),
                }
            (models_dir / "manifest.json").write_text(json.dumps({
                "schema_version": 1, "models": old_models,
            }), encoding="utf-8")
            results = update_models(
                "https://example.test/api/gachalog-zc/get-model-manifest",
                models_dir, "1.0.0", login_token="test-token", client=client,
            )
            for name in ("image_type", "gacha10"):
                self.assertEqual(results[name].status, "downloaded")
                self.assertEqual((models_dir / f"{name}.onnx").read_bytes(), files[name])
                self.assertEqual((models_dir / f"{name}.keras").read_bytes(), b"old-keras")

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
            "gacha10.onnx",
            32 * MEBIBYTE,
            10,
            16,
            5,
        )

        self.assertEqual(
            status,
            "完成 gacha10.onnx      32.00 MiB  用时 00:10  平均    3.20 MiB/s",
        )

    def _client(self, files, versions=None, corrupt_download=False):
        versions = versions or {name: "2026.09.02.1" for name in files}

        def handler(request):
            self.assertEqual(request.headers.get("authorization"), "Bearer test-token")
            if request.url.path == "/api/gachalog-zc/get-model-manifest":
                models = {}
                for name, content in files.items():
                    models[name] = {
                        "version": versions[name],
                        "sha256": hashlib.sha256(content).hexdigest(),
                        "size": len(content),
                        "url": f"/api/gachalog-zc/download-model?model_name={name}&version={versions[name]}",
                        "min_client_version": "0.2.0",
                    }
                return httpx.Response(
                    200, json={"schema_version": 1, "models": models}
                )
            self.assertEqual(request.url.path, "/api/gachalog-zc/download-model")
            name = request.url.params["model_name"]
            self.assertEqual(request.url.params["version"], versions[name])
            content = b"corrupt" if corrupt_download else files[name]
            return httpx.Response(200, content=content)

        return httpx.Client(transport=httpx.MockTransport(handler))

    def test_downloads_missing_models_and_writes_manifest(self):
        files = {
            "image_type": b"image-model",
            "gacha10": b"gacha-model",
            "operators": "能天使\n推进之王\n".encode(),
        }
        with tempfile.TemporaryDirectory() as temp_dir, self._client(files) as client:
            models_dir = pathlib.Path(temp_dir)
            results = update_models(
                "https://example.test/api/gachalog-zc/get-model-manifest",
                models_dir,
                "0.2.0",
                login_token="test-token",
                client=client,
            )

            self.assertEqual(results["image_type"].status, "downloaded")
            self.assertEqual((models_dir / "image_type.onnx").read_bytes(), files["image_type"])
            self.assertEqual(
                (models_dir / "operators.txt").read_bytes(), files["operators"]
            )
            manifest = json.loads((models_dir / "manifest.json").read_text("utf-8"))
            self.assertEqual(manifest["models"]["gacha10"]["version"], "2026.09.02.1")

    def test_matching_legacy_files_are_not_downloaded(self):
        files = {
            "image_type": b"image-model",
            "gacha10": b"gacha-model",
            "operators": "能天使\n推进之王\n".encode(),
        }
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
            for name, filename in {
                "image_type": "image_type.onnx",
                "gacha10": "gacha10.onnx",
                "operators": "operators.txt",
            }.items():
                (models_dir / filename).write_bytes(files[name])
            with httpx.Client(transport=httpx.MockTransport(handler)) as client:
                results = update_models(
                    "https://example.test/api/gachalog-zc/get-model-manifest",
                    models_dir,
                    "0.2.0",
                    client=client,
                )

            self.assertEqual(requests, ["/api/gachalog-zc/get-model-manifest"])
            self.assertTrue(all(result.status == "current" for result in results.values()))

    def test_bad_download_does_not_replace_existing_model(self):
        files = {
            "image_type": b"new-image",
            "gacha10": b"new-gacha",
            "operators": "能天使\n推进之王\n".encode(),
        }
        with tempfile.TemporaryDirectory() as temp_dir, self._client(
            files, corrupt_download=True
        ) as client:
            models_dir = pathlib.Path(temp_dir)
            old_model = models_dir / "image_type.onnx"
            old_model.write_bytes(b"old-image")

            with self.assertRaises(ValueError):
                update_models(
                    "https://example.test/api/gachalog-zc/get-model-manifest",
                    models_dir,
                    "0.2.0",
                    login_token="test-token",
                    client=client,
                )

            self.assertEqual(old_model.read_bytes(), b"old-image")

    def test_invalid_operator_list_does_not_replace_existing_file(self):
        files = {
            "image_type": b"image-model",
            "gacha10": b"gacha-model",
            "operators": "能天使\n能天使\n".encode(),
        }
        with tempfile.TemporaryDirectory() as temp_dir, self._client(files) as client:
            models_dir = pathlib.Path(temp_dir)
            old_operators = models_dir / "operators.txt"
            old_operators.write_text("推进之王\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "干员类别表存在重复项"):
                update_models(
                    "https://example.test/api/gachalog-zc/get-model-manifest",
                    models_dir,
                    "0.2.0",
                    login_token="test-token",
                    client=client,
                )

            self.assertEqual(old_operators.read_text(encoding="utf-8"), "推进之王\n")


if __name__ == "__main__":
    unittest.main()
