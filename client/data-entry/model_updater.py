import hashlib
import json
import math
import os
import pathlib
import tempfile
import time
from dataclasses import dataclass
from typing import Dict, Mapping, Optional, Tuple
from urllib.parse import urljoin

import httpx


MANIFEST_SCHEMA_VERSION = 1
DEFAULT_MODEL_FILES = {
    "image_type": "image_type.onnx",
    "gacha10": "gacha10.onnx",
    "operators": "operators.txt",
}
MEBIBYTE = 1024 * 1024


@dataclass(frozen=True)
class ModelUpdateResult:
    name: str
    version: str
    status: str


def _version_key(version: str) -> Tuple[int, ...]:
    """将 2026.09.02.1 形式的版本转换成可比较的数字元组。"""
    if not isinstance(version, str) or not version:
        raise ValueError("模型版本不能为空")
    parts = version.split(".")
    if any(not part.isdigit() for part in parts):
        raise ValueError(f"不支持的模型版本格式: {version}")
    return tuple(int(part) for part in parts)


def _sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as model_file:
        for chunk in iter(lambda: model_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_downloaded_file(path: pathlib.Path, destination_name: str) -> None:
    if destination_name != "operators.txt":
        return
    try:
        operator_names = [
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except UnicodeDecodeError as error:
        raise ValueError("干员类别表不是有效的 UTF-8 文本") from error
    if not operator_names:
        raise ValueError("干员类别表不能为空")
    if len(operator_names) != len(set(operator_names)):
        raise ValueError("干员类别表存在重复项")


def _format_download_status(
    model_name: str,
    downloaded_size: int,
    expected_size: int,
    speed: float,
    model_name_width: int,
    size_width: int,
) -> str:
    progress = min(downloaded_size / expected_size * 100, 100) if expected_size else 100
    remaining_size = max(expected_size - downloaded_size, 0)
    eta_seconds = math.ceil(remaining_size / speed) if speed > 0 else 0
    eta_minutes, eta_seconds = divmod(min(eta_seconds, 5999), 60)
    return (
        f"下载 {model_name:<{model_name_width}}  "
        f"{downloaded_size / MEBIBYTE:>{size_width}.2f}/"
        f"{expected_size / MEBIBYTE:>{size_width}.2f} MiB  "
        f"{progress:>5.1f}%  "
        f"{speed / MEBIBYTE:>7.2f} MiB/s  "
        f"剩余 {eta_minutes:02d}:{eta_seconds:02d}"
    )


def _format_download_complete(
    model_name: str,
    downloaded_size: int,
    elapsed: float,
    model_name_width: int,
    size_width: int,
) -> str:
    average_speed = downloaded_size / elapsed if elapsed > 0 else 0
    elapsed_seconds = math.ceil(elapsed)
    elapsed_minutes, elapsed_seconds = divmod(min(elapsed_seconds, 5999), 60)
    return (
        f"完成 {model_name:<{model_name_width}}  "
        f"{downloaded_size / MEBIBYTE:>{size_width}.2f} MiB  "
        f"用时 {elapsed_minutes:02d}:{elapsed_seconds:02d}  "
        f"平均 {average_speed / MEBIBYTE:>7.2f} MiB/s"
    )


def _load_local_manifest(path: pathlib.Path) -> dict:
    try:
        with path.open("r", encoding="utf-8") as manifest_file:
            manifest = json.load(manifest_file)
        if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
            return {"schema_version": MANIFEST_SCHEMA_VERSION, "models": {}}
        if not isinstance(manifest.get("models"), dict):
            return {"schema_version": MANIFEST_SCHEMA_VERSION, "models": {}}
        return manifest
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {"schema_version": MANIFEST_SCHEMA_VERSION, "models": {}}


def _write_local_manifest(path: pathlib.Path, manifest: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix="manifest-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as manifest_file:
            json.dump(manifest, manifest_file, ensure_ascii=False, indent=2)
            manifest_file.write("\n")
            manifest_file.flush()
            os.fsync(manifest_file.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def _validate_remote_manifest(manifest: dict) -> Mapping[str, dict]:
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise ValueError("服务器返回了不支持的模型清单版本")
    models = manifest.get("models")
    if not isinstance(models, dict):
        raise ValueError("服务器模型清单缺少 models")
    return models


def _download_and_replace(
    client: httpx.Client,
    download_url: str,
    destination: pathlib.Path,
    expected_sha256: str,
    expected_size: int,
    headers: Mapping[str, str],
    model_name_width: int,
    size_width: int,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f"{destination.name}-", suffix=".download", dir=destination.parent
    )
    digest = hashlib.sha256()
    downloaded_size = 0
    start_time = time.monotonic()
    last_report_size = 0
    last_report_time = start_time
    smoothed_speed = None
    progress_line_active = False
    progress_line_length = 0
    try:
        with os.fdopen(fd, "wb") as output_file:
            with client.stream("GET", download_url, headers=headers) as response:
                response.raise_for_status()
                for chunk in response.iter_bytes(1024 * 1024):
                    output_file.write(chunk)
                    digest.update(chunk)
                    downloaded_size += len(chunk)
                    now = time.monotonic()
                    interval = now - last_report_time
                    if interval >= 0.5:
                        current_speed = (downloaded_size - last_report_size) / interval
                        smoothed_speed = (
                            current_speed
                            if smoothed_speed is None
                            else 0.25 * current_speed + 0.75 * smoothed_speed
                        )
                        status_line = _format_download_status(
                            destination.name,
                            downloaded_size,
                            expected_size,
                            smoothed_speed,
                            model_name_width,
                            size_width,
                        )
                        print("\r" + status_line, end="", flush=True)
                        progress_line_active = True
                        progress_line_length = len(status_line)
                        last_report_size = downloaded_size
                        last_report_time = now

            output_file.flush()
            os.fsync(output_file.fileno())

        elapsed = max(time.monotonic() - start_time, 0.001)
        if downloaded_size != expected_size:
            raise ValueError(
                f"模型 {destination.name} 大小不符: "
                f"期望 {expected_size}，实际 {downloaded_size}"
            )
        actual_sha256 = digest.hexdigest()
        if actual_sha256 != expected_sha256:
            raise ValueError(f"模型 {destination.name} SHA-256 校验失败")
        _validate_downloaded_file(pathlib.Path(temp_name), destination.name)
        os.replace(temp_name, destination)
        complete_line = _format_download_complete(
            destination.name,
            downloaded_size,
            elapsed,
            model_name_width,
            size_width,
        )
        print("\r" + complete_line.ljust(progress_line_length))
        progress_line_active = False
    except Exception:
        if progress_line_active:
            print()
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def update_models(
    manifest_url: str,
    models_dir: pathlib.Path,
    client_version: str,
    login_token: Optional[str] = None,
    model_files: Mapping[str, str] = DEFAULT_MODEL_FILES,
    client: Optional[httpx.Client] = None,
) -> Dict[str, ModelUpdateResult]:
    """从服务器清单检查并更新模型，成功后返回每个模型的处理结果。"""
    models_dir = pathlib.Path(models_dir)
    local_manifest_path = models_dir / "manifest.json"
    local_manifest = _load_local_manifest(local_manifest_path)
    headers = {"Authorization": f"Bearer {login_token}"} if login_token else {}
    owns_client = client is None
    http_client = client or httpx.Client(http2=True, timeout=httpx.Timeout(30, read=300))

    try:
        response = http_client.get(manifest_url, headers=headers)
        response.raise_for_status()
        remote_models = _validate_remote_manifest(response.json())
        results: Dict[str, ModelUpdateResult] = {}
        model_name_width = max(len(filename) for filename in model_files.values())
        remote_sizes = [
            model.get("size", 0)
            for name, model in remote_models.items()
            if name in model_files and isinstance(model, dict)
        ]
        largest_size = max(remote_sizes, default=0)
        size_width = max(len(f"{largest_size / MEBIBYTE:.2f}"), 4)

        for name, filename in model_files.items():
            remote = remote_models.get(name)
            if not isinstance(remote, dict):
                raise ValueError(f"服务器模型清单缺少 {name}")

            version = remote.get("version")
            sha256 = remote.get("sha256")
            size = remote.get("size")
            download_url = remote.get("url")
            min_client_version = remote.get("min_client_version", "0")
            _version_key(version)
            if not isinstance(sha256, str) or len(sha256) != 64:
                raise ValueError(f"模型 {name} 的 SHA-256 无效")
            if not isinstance(size, int) or size < 0:
                raise ValueError(f"模型 {name} 的文件大小无效")
            if not isinstance(download_url, str) or not download_url:
                raise ValueError(f"模型 {name} 缺少下载地址")
            if _version_key(client_version) < _version_key(min_client_version):
                raise RuntimeError(
                    f"模型 {name} {version} 要求客户端至少为 {min_client_version}，"
                    f"当前为 {client_version}"
                )

            destination = models_dir / filename
            local = local_manifest["models"].get(name, {})
            local_version = local.get("version")
            actual_sha256 = _sha256(destination) if destination.is_file() else None
            should_download = actual_sha256 != sha256

            if local_version:
                local_key = _version_key(local_version)
                remote_key = _version_key(version)
                if (
                    remote_key < local_key
                    and actual_sha256 is not None
                    and actual_sha256 == local.get("sha256")
                ):
                    results[name] = ModelUpdateResult(name, local_version, "kept-newer-local")
                    continue

            if should_download:
                _download_and_replace(
                    http_client,
                    urljoin(manifest_url, download_url),
                    destination,
                    sha256,
                    size,
                    headers,
                    model_name_width,
                    size_width,
                )
                status = "downloaded"
            else:
                status = "current"

            local_manifest["models"][name] = {
                "version": version,
                "sha256": sha256,
                "size": size,
            }
            results[name] = ModelUpdateResult(name, version, status)

        _write_local_manifest(local_manifest_path, local_manifest)
        return results
    finally:
        if owns_client:
            http_client.close()


def ensure_latest_models(
    manifest_url: str,
    models_dir: pathlib.Path,
    client_version: str,
    login_token: Optional[str] = None,
    model_files: Mapping[str, str] = DEFAULT_MODEL_FILES,
) -> Dict[str, ModelUpdateResult]:
    """更新失败时，仅在全部本地模型仍然存在的情况下允许离线启动。"""
    try:
        return update_models(
            manifest_url,
            models_dir,
            client_version,
            login_token=login_token,
            model_files=model_files,
        )
    except Exception as exc:
        missing = [
            name
            for name, filename in model_files.items()
            if not (pathlib.Path(models_dir) / filename).is_file()
        ]
        if missing:
            raise RuntimeError(
                f"无法获取模型，且本地缺少: {', '.join(missing)}"
            ) from exc
        print(f"检查模型更新失败，将继续使用本地模型: {exc}")
        return {}
