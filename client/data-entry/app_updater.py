"""Check for data-entry releases and apply an update after the GUI exits."""

import argparse
import ast
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time
import traceback
import uuid
import zipfile
from urllib.parse import unquote, urlsplit


REPOSITORY = "325-Gaming/zc-flight-statistics"
RELEASES_URL = f"https://api.github.com/repos/{REPOSITORY}/releases?per_page=100"
UPDATE_POLICY_URL = (
    "https://raw.githubusercontent.com/325-Gaming/zc-flight-statistics/"
    "master/update-policy.json"
)
VERSION_SOURCE_URL = (
    "https://raw.githubusercontent.com/325-Gaming/zc-flight-statistics/"
    "master/client/data-entry/version.py"
)
TAG_PATTERN = re.compile(r"data-entry/v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")
VERSION_PATTERN = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")
MAX_POLICY_SIZE = 16 * 1024
MAX_VERSION_SOURCE_SIZE = 4 * 1024
MAX_RELEASES_SIZE = 5 * 1024 * 1024
MAX_ARCHIVE_SIZE = 100 * 1024 * 1024
MAX_UNPACKED_SIZE = 150 * 1024 * 1024
MAX_POLICY_MESSAGE_LENGTH = 500
PROTECTED_NAMES = {".env", "config.json", "name.csv", "release-manifest.json"}
PROTECTED_ROOTS = {".git", ".runtime", ".venv", "models"}
WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{n}" for n in range(1, 10)),
                    *(f"LPT{n}" for n in range(1, 10))}


def _version_from_source(source):
    try:
        module = ast.parse(source, filename="version.py")
    except SyntaxError as error:
        raise ValueError("version.py 语法无效") from error
    for statement in module.body:
        if isinstance(statement, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__version__"
            for target in statement.targets
        ):
            if isinstance(statement.value, ast.Constant) and isinstance(statement.value.value, str):
                return statement.value.value
    raise ValueError("version.py 中没有有效的版本号")


def _version_tuple(version):
    match = VERSION_PATTERN.fullmatch(version) if isinstance(version, str) else None
    if match is None:
        raise ValueError("版本号格式无效")
    return tuple(map(int, match.groups()))


def version_is_at_least(version, minimum):
    return _version_tuple(version) >= _version_tuple(minimum)


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("更新策略包含重复字段")
        result[key] = value
    return result


def validate_update_policy(payload):
    try:
        policy = json.loads(payload.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise ValueError("官方更新策略不是有效的 UTF-8 JSON") from error
    except ValueError:
        raise
    if not isinstance(policy, dict) or set(policy) != {"data-entry"}:
        raise ValueError("官方更新策略结构无效")
    entry = policy["data-entry"]
    if not isinstance(entry, dict) or set(entry) != {
        "schema_version", "minimum_supported_version", "message",
    }:
        raise ValueError("data-entry 更新策略字段缺失或包含未知字段")
    schema_version = entry["schema_version"]
    if type(schema_version) is not int or schema_version != 1:
        raise ValueError("不支持的更新策略 schema_version")
    minimum = entry["minimum_supported_version"]
    if not isinstance(minimum, str) or len(minimum) > 64:
        raise ValueError("最低支持版本必须是有效的 MAJOR.MINOR.PATCH 字符串")
    _version_tuple(minimum)
    message = entry["message"]
    if (
        not isinstance(message, str) or not message.strip()
        or len(message) > MAX_POLICY_MESSAGE_LENGTH
        or any(ord(character) < 32 and character not in "\t\n\r" for character in message)
    ):
        raise ValueError("更新策略 message 必须是 1 到 500 字符的可读文本")
    return {
        "schema_version": schema_version,
        "minimum_supported_version": minimum,
        "message": message,
    }


def fetch_update_policy():
    import httpx

    timeout = httpx.Timeout(connect=5, read=10, write=5, pool=5)
    try:
        with httpx.stream(
            "GET", UPDATE_POLICY_URL, follow_redirects=False, timeout=timeout,
            headers={"Accept": "application/json"},
        ) as response:
            if response.status_code != 200:
                raise ValueError(f"官方更新策略请求失败（HTTP {response.status_code}）")
            length = response.headers.get("content-length")
            if length is not None:
                try:
                    if int(length) < 0 or int(length) > MAX_POLICY_SIZE:
                        raise ValueError("官方更新策略响应超出大小限制")
                except ValueError as error:
                    if str(error) == "官方更新策略响应超出大小限制":
                        raise
                    raise ValueError("官方更新策略 Content-Length 无效") from error
            payload = bytearray()
            for chunk in response.iter_bytes():
                payload.extend(chunk)
                if len(payload) > MAX_POLICY_SIZE:
                    raise ValueError("官方更新策略响应超出大小限制")
    except httpx.TimeoutException as error:
        raise ValueError("连接或读取官方更新策略超时") from error
    except httpx.HTTPError as error:
        raise ValueError("无法连接官方更新策略服务") from error
    return validate_update_policy(bytes(payload))


def validate_version_source(payload):
    if not isinstance(payload, bytes) or len(payload) > MAX_VERSION_SOURCE_SIZE:
        raise ValueError("官方 version.py 响应无效或超出大小限制")
    try:
        source = payload.decode("utf-8")
        module = ast.parse(source, filename="version.py")
    except (UnicodeDecodeError, SyntaxError, RecursionError) as error:
        raise ValueError("官方 version.py 不是有效的 UTF-8 Python 文件") from error

    assignments = []
    for statement in module.body:
        if isinstance(statement, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__version__"
            for target in statement.targets
        ):
            if (
                len(statement.targets) != 1
                or not isinstance(statement.targets[0], ast.Name)
                or statement.targets[0].id != "__version__"
                or not isinstance(statement.value, ast.Constant)
                or not isinstance(statement.value.value, str)
            ):
                raise ValueError("官方 version.py 的版本号声明无效")
            assignments.append(statement.value.value)
        elif isinstance(statement, ast.AnnAssign) and (
            isinstance(statement.target, ast.Name)
            and statement.target.id == "__version__"
        ):
            raise ValueError("官方 version.py 的版本号声明无效")
    if len(assignments) != 1:
        raise ValueError("官方 version.py 必须且只能包含一个静态版本号")
    _version_tuple(assignments[0])
    return assignments[0]


def fetch_official_version():
    import httpx

    timeout = httpx.Timeout(connect=5, read=10, write=5, pool=5)
    try:
        with httpx.stream(
            "GET", VERSION_SOURCE_URL, follow_redirects=False, timeout=timeout,
            headers={"Accept": "text/plain"},
        ) as response:
            if response.status_code != 200:
                raise ValueError(f"官方 version.py 请求失败（HTTP {response.status_code}）")
            length = response.headers.get("content-length")
            if length is not None:
                try:
                    size = int(length)
                except ValueError as error:
                    raise ValueError("官方 version.py Content-Length 无效") from error
                if size < 0 or size > MAX_VERSION_SOURCE_SIZE:
                    raise ValueError("官方 version.py 响应超出大小限制")
            payload = bytearray()
            for chunk in response.iter_bytes():
                payload.extend(chunk)
                if len(payload) > MAX_VERSION_SOURCE_SIZE:
                    raise ValueError("官方 version.py 响应超出大小限制")
    except httpx.TimeoutException as error:
        raise ValueError("连接或读取官方 version.py 超时") from error
    except httpx.HTTPError as error:
        raise ValueError("无法连接官方 version.py 服务") from error
    return validate_version_source(bytes(payload))


def _git(root, *args):
    try:
        result = subprocess.run(
            ["git", *args], cwd=root, check=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180,
        )
    except subprocess.CalledProcessError as error:
        detail = error.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"Git 操作失败：{detail or '请检查仓库和网络连接'}") from error
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("Git 操作超时，请检查网络连接") from error
    return result.stdout.decode("utf-8", errors="replace").strip()


def _git_root(base_dir):
    root = base_dir.parent.parent
    if shutil.which("git") is None:
        return None
    try:
        actual = pathlib.Path(_git(root, "rev-parse", "--show-toplevel")).resolve()
    except (OSError, RuntimeError):
        return None
    return actual if actual == root.resolve() else None


def _check_git(base_dir, current_version, root):
    branch = _git(root, "branch", "--show-current")
    if not branch:
        raise ValueError("当前 Git 仓库处于 detached HEAD，无法自动更新")
    remote = _git(root, "config", "--get", f"branch.{branch}.remote")
    if not remote or remote == ".":
        raise ValueError("当前 Git 分支没有远端上游")
    upstream = _git(root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
    if _git(root, "status", "--porcelain", "--untracked-files=no"):
        raise ValueError("仓库有未提交的受版本管理文件，请先处理后再更新")
    _git(root, "fetch", "--no-tags", remote)
    current = _git(root, "rev-parse", "HEAD")
    target = _git(root, "rev-parse", upstream)
    if current == target:
        return {"available": False, "mode": "git", "current_version": current_version}
    if subprocess.run(
        ["git", "merge-base", "--is-ancestor", current, target], cwd=root,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ).returncode != 0:
        raise ValueError("本地分支与上游已分叉，无法自动快进更新")
    if not _git(root, "diff", "--name-only", current, target, "--", "client/data-entry"):
        return {"available": False, "mode": "git", "current_version": current_version}
    source = _git(root, "show", f"{target}:client/data-entry/version.py")
    version = _version_from_source(source)
    if _version_tuple(version) < _version_tuple(current_version):
        raise ValueError("远端代码的客户端版本低于当前版本，已取消更新")
    return {
        "available": True, "mode": "git", "current_version": current_version,
        "version": version, "commit": target, "root": str(root),
        "requirements_changed": bool(_git(
            root, "diff", "--name-only", current, target, "--",
            "client/data-entry/requirements.txt",
        )),
    }


def _release_data():
    import httpx

    timeout = httpx.Timeout(connect=5, read=15, write=5, pool=5)
    payload = bytearray()
    try:
        with httpx.stream(
            "GET", RELEASES_URL, headers={"Accept": "application/vnd.github+json"},
            follow_redirects=True, timeout=timeout,
        ) as response:
            if response.status_code != 200:
                raise ValueError(f"GitHub Release 检查失败（HTTP {response.status_code}）")
            length = response.headers.get("content-length")
            if length is not None:
                try:
                    if int(length) < 0:
                        raise ValueError
                    if int(length) > MAX_RELEASES_SIZE:
                        raise ValueError("GitHub Release 列表响应过大")
                except ValueError as error:
                    if str(error) == "GitHub Release 列表响应过大":
                        raise
                    raise ValueError("GitHub Release Content-Length 无效") from error
            for chunk in response.iter_bytes():
                payload.extend(chunk)
                if len(payload) > MAX_RELEASES_SIZE:
                    raise ValueError("GitHub Release 列表响应过大")
    except httpx.TimeoutException as error:
        raise ValueError("GitHub Release 检查超时") from error
    except httpx.HTTPError as error:
        raise ValueError("无法连接 GitHub Release 服务") from error
    try:
        releases = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise ValueError("GitHub Release 返回的数据格式无效") from error
    if not isinstance(releases, list):
        raise ValueError("GitHub Release 返回的数据格式无效")
    return releases


def _check_release(current_version, minimum_version=None, include_current=False):
    current_tuple = _version_tuple(current_version)
    minimum_tuple = _version_tuple(minimum_version) if minimum_version is not None else None
    releases = _release_data()
    candidates = []
    for release in releases:
        if (not isinstance(release, dict) or release.get("draft") is not False
                or release.get("prerelease") is not False):
            continue
        tag = release.get("tag_name", "")
        match = TAG_PATTERN.fullmatch(tag) if isinstance(tag, str) else None
        if match is None:
            continue
        version_tuple = tuple(map(int, match.groups()))
        if minimum_tuple is not None and version_tuple < minimum_tuple:
            continue
        if version_tuple < current_tuple or (version_tuple == current_tuple and not include_current):
            continue
        candidates.append((version_tuple, release))
    if not candidates:
        if minimum_tuple is not None and current_tuple < minimum_tuple:
            raise ValueError(
                f"没有可验证的稳定版 Release 达到最低支持版本 {minimum_version}"
            )
        return {"available": False, "mode": "release", "current_version": current_version}
    version_parts, release = max(candidates, key=lambda item: item[0])
    version = ".".join(map(str, version_parts))
    tag = release["tag_name"]
    filename = f"data-entry-v{version}.zip"
    assets = release.get("assets")
    if not isinstance(assets, list):
        assets = []
    asset = next((item for item in assets
                  if isinstance(item, dict) and item.get("name") == filename), None)
    if asset is None or asset.get("state") != "uploaded":
        if minimum_tuple is not None and current_tuple >= minimum_tuple and not include_current:
            return {"available": False, "mode": "release", "current_version": current_version}
        raise ValueError(f"新版 {version} 尚未提供 {filename}")
    url = asset.get("browser_download_url")
    parsed = urlsplit(url) if isinstance(url, str) else None
    if (parsed is None or parsed.scheme != "https" or parsed.netloc != "github.com"
            or parsed.query or parsed.fragment or
            unquote(parsed.path) != f"/{REPOSITORY}/releases/download/{tag}/{filename}"):
        if minimum_tuple is not None and current_tuple >= minimum_tuple and not include_current:
            return {"available": False, "mode": "release", "current_version": current_version}
        raise ValueError("GitHub Release 下载地址无效")
    size = asset.get("size")
    if type(size) is not int or not 0 < size <= MAX_ARCHIVE_SIZE:
        if minimum_tuple is not None and current_tuple >= minimum_tuple and not include_current:
            return {"available": False, "mode": "release", "current_version": current_version}
        raise ValueError("GitHub Release 压缩包大小无效")
    digest = asset.get("digest")
    if digest is not None and (
        not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
    ):
        if minimum_tuple is not None and current_tuple >= minimum_tuple and not include_current:
            return {"available": False, "mode": "release", "current_version": current_version}
        raise ValueError("GitHub Release 文件校验值无效")
    return {
        "available": True, "mode": "release", "current_version": current_version,
        "version": version, "tag": tag, "url": url, "size": size, "digest": digest,
        **({"minimum_version": minimum_version} if minimum_version is not None else {}),
    }


def check_startup_update(
    current_version, minimum_version, force_repair=False, official_version=None,
):
    current_tuple = _version_tuple(current_version)
    minimum_tuple = _version_tuple(minimum_version)
    required = current_tuple < minimum_tuple or force_repair
    if required:
        offer = _check_release(
            current_version, minimum_version=minimum_version,
            include_current=force_repair,
        )
    else:
        if (
            official_version is None
            or _version_tuple(official_version) <= current_tuple
        ):
            return {
                "required": False,
                "offer": {
                    "available": False,
                    "mode": "release",
                    "current_version": current_version,
                },
            }
        try:
            offer = _check_release(current_version, minimum_version=minimum_version)
        except ValueError as error:
            return {
                "required": False,
                "offer": {
                    "available": False,
                    "mode": "release",
                    "current_version": current_version,
                },
                "check_error": str(error),
            }
        if not offer.get("available"):
            return {"required": False, "offer": offer}
        target_tuple = _version_tuple(offer["version"])
        if target_tuple < minimum_tuple or target_tuple <= current_tuple:
            return {
                "required": False,
                "offer": {
                    "available": False,
                    "mode": "release",
                    "current_version": current_version,
                },
            }
        return {"required": False, "offer": offer}

    if not offer.get("available"):
        raise ValueError("没有可验证的稳定版 Release 可用于完成强制更新")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", offer.get("digest") or ""):
        raise ValueError("强制更新目标缺少有效的 SHA-256 校验值")
    target_tuple = _version_tuple(offer["version"])
    if target_tuple < minimum_tuple or target_tuple < current_tuple:
        raise ValueError("更新目标版本无法满足最低支持版本")
    if target_tuple == current_tuple and not force_repair:
        raise ValueError("官方更新目标版本未达到最低支持版本")
    if force_repair:
        offer["force_dependencies"] = True
    return {"required": True, "offer": offer}


def check_update(base_dir, current_version):
    base_dir = pathlib.Path(base_dir).resolve()
    git_marker = base_dir.parent.parent / ".git"
    if git_marker.exists() and shutil.which("git") is None:
        raise ValueError("此安装属于 Git 仓库，但系统中没有可用的 git 命令")
    root = _git_root(base_dir)
    if git_marker.exists() and root is None:
        raise ValueError("无法识别当前 Git 仓库，请检查仓库状态")
    if root is not None and not (base_dir / "release-manifest.json").exists():
        return _check_git(base_dir, current_version, root)
    return _check_release(current_version)


def _safe_name(name):
    if name == "models/.gitkeep":
        return True
    return (
        bool(name) and "\\" not in name and not name.startswith("/")
        and all(re.fullmatch(r"[A-Za-z0-9_.-]+", part) and part not in {".", ".."}
                and not part.endswith(".") and part.split(".", 1)[0].upper() not in WINDOWS_RESERVED
                for part in name.split("/"))
        and name.split("/", 1)[0].casefold() not in PROTECTED_ROOTS
        and name.casefold() not in PROTECTED_NAMES
    )


def _validate_archive(path, expected_tag):
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        names = [entry.filename for entry in entries]
        if len(names) != len(set(names)) or len(names) != len({name.casefold() for name in names}) or "release-manifest.json" not in names:
            raise ValueError("发布包缺少清单或包含重复文件")
        if len(entries) > 300 or sum(entry.file_size for entry in entries) > MAX_UNPACKED_SIZE:
            raise ValueError("发布包内容过大")
        manifest = json.loads(archive.read("release-manifest.json"))
        if (not isinstance(manifest, dict) or type(manifest.get("schema_version")) is not int
                or manifest.get("schema_version") != 1):
            raise ValueError("发布包清单格式无效")
        match = TAG_PATTERN.fullmatch(expected_tag)
        if (match is None or manifest.get("tag") != expected_tag
                or manifest.get("version") != ".".join(match.groups())
                or not isinstance(manifest.get("commit"), str)
                or not re.fullmatch(r"[0-9a-f]{40,64}", manifest["commit"])):
            raise ValueError("发布包版本与所选 Release 不一致")
        hashes = manifest.get("files")
        if not isinstance(hashes, dict) or set(names) != set(hashes) | {"release-manifest.json"}:
            raise ValueError("发布包文件与清单不一致")
        if "version.py" not in hashes:
            raise ValueError("发布包缺少 version.py")
        files = {}
        for entry in entries:
            name = entry.filename
            if name == "release-manifest.json":
                continue
            mode = (entry.external_attr >> 16) & 0o170000
            if not _safe_name(name) or entry.is_dir() or mode not in {0, 0o100000}:
                raise ValueError(f"发布包包含不安全路径：{name}")
            expected = hashes[name]
            if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
                raise ValueError(f"发布包文件校验值无效：{name}")
            contents = archive.read(entry)
            if hashlib.sha256(contents).hexdigest() != expected:
                raise ValueError(f"发布包文件校验失败：{name}")
            files[name] = contents
        if _version_from_source(files["version.py"]) != manifest["version"]:
            raise ValueError("发布包 version.py 与标签版本不一致")
        return files, manifest


def _download_release(offer, destination, cancelled=lambda: False):
    import httpx

    digest = hashlib.sha256()
    count = 0
    try:
        with httpx.stream("GET", offer["url"], follow_redirects=True, timeout=90) as response:
            response.raise_for_status()
            with destination.open("wb") as output:
                for chunk in response.iter_bytes():
                    if cancelled():
                        raise RuntimeError("更新已取消")
                    count += len(chunk)
                    if count > MAX_ARCHIVE_SIZE or count > offer["size"]:
                        raise ValueError("下载的发布包超出预期大小")
                    digest.update(chunk)
                    output.write(chunk)
    except httpx.TimeoutException as error:
        raise ValueError("Release 下载超时") from error
    except httpx.HTTPStatusError as error:
        raise ValueError(f"Release 下载失败（HTTP {error.response.status_code}）") from error
    except httpx.HTTPError as error:
        raise ValueError("无法连接 Release 文件服务") from error
    if count != offer["size"]:
        raise ValueError("下载的发布包大小与 GitHub Release 不一致")
    if offer["digest"] and digest.hexdigest() != offer["digest"].removeprefix("sha256:"):
        raise ValueError("下载的发布包 SHA-256 与 GitHub Release 不一致")
    _validate_archive(destination, offer["tag"])


def start_update(base_dir, offer, parent_pid, argv, cancelled=lambda: False):
    base_dir = pathlib.Path(base_dir).resolve()
    if offer.get("mode") == "release":
        version = _version_tuple(offer.get("version"))
        minimum = offer.get("minimum_version")
        if minimum is not None and version < _version_tuple(minimum):
            raise ValueError("更新目标版本低于官方最低支持版本")
        if offer.get("tag") != f"data-entry/v{offer['version']}":
            raise ValueError("更新目标标签与版本不一致")
    runtime = base_dir / ".runtime"
    if runtime.is_symlink():
        raise ValueError("更新运行目录不能是符号链接")
    runtime.mkdir(parents=True, exist_ok=True)
    stage = runtime / f"update-{uuid.uuid4().hex}"
    stage.mkdir()
    try:
        if offer["mode"] == "release":
            _download_release(offer, stage / "release.zip", cancelled=cancelled)
        elif offer["mode"] == "git":
            root = _git_root(base_dir)
            if root is None or str(root) != offer["root"]:
                raise ValueError("Git 安装状态已变化，请重新检查更新")
            if _git(root, "status", "--porcelain", "--untracked-files=no"):
                raise ValueError("仓库有未提交的受版本管理文件，请先处理后再更新")
            if _git(root, "rev-parse", "HEAD") == offer["commit"]:
                raise ValueError("当前代码已是新版，请重新检查更新")
        else:
            raise ValueError("更新来源无效")
        if cancelled():
            raise RuntimeError("更新已取消")
        shutil.copy2(__file__, stage / "update_helper.py")
        plan = {
            "base_dir": str(base_dir), "offer": offer, "parent_pid": parent_pid,
            "executable": sys.executable,
            "argv": [str(base_dir / "webview_app.py"), *argv[1:]],
        }
        (stage / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
        log = (runtime / "update.log").open("a", encoding="utf-8")
        try:
            subprocess.Popen(
                [sys.executable, str(stage / "update_helper.py"), "--plan", str(stage / "plan.json")],
                cwd=base_dir, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                start_new_session=sys.platform != "win32",
            )
        finally:
            log.close()
    except Exception as error:
        shutil.rmtree(stage, ignore_errors=True)
        if isinstance(error, zipfile.BadZipFile):
            raise ValueError("下载的发布包不是有效 ZIP 文件") from error
        raise


def _wait_for_exit(pid):
    if sys.platform == "win32":
        import ctypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
        kernel.WaitForSingleObject.restype = ctypes.c_uint32
        kernel.CloseHandle.argtypes = (ctypes.c_void_p,)
        handle = kernel.OpenProcess(0x00100000, False, pid)
        if not handle:
            if ctypes.get_last_error() == 87:  # ERROR_INVALID_PARAMETER: already exited.
                return
            raise OSError(ctypes.get_last_error(), "无法等待旧版客户端退出")
        try:
            result = kernel.WaitForSingleObject(handle, 120000)
            if result == 0x102:
                raise TimeoutError("等待旧版客户端退出超时")
            if result != 0:
                raise OSError(ctypes.get_last_error(), "等待旧版客户端退出失败")
        finally:
            kernel.CloseHandle(handle)
        return
    for _ in range(240):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.5)
    raise TimeoutError("等待旧版客户端退出超时")


def _check_local_files(base_dir):
    manifest_path = base_dir / "release-manifest.json"
    if manifest_path.is_symlink():
        raise ValueError("现有安装清单不能是符号链接")
    if not manifest_path.exists():
        return set()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    hashes = manifest.get("files") if isinstance(manifest, dict) else None
    if not isinstance(hashes, dict):
        raise ValueError("现有安装清单无效")
    for name, expected in hashes.items():
        if not isinstance(name, str) or not _safe_name(name) or not isinstance(expected, str):
            raise ValueError("现有安装清单包含不安全文件")
        target = base_dir / name
        if target.is_symlink() or (target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() != expected):
            raise ValueError(f"本地程序文件已修改，无法自动覆盖：{name}")
    return set(hashes)


def _write_json_atomically(path, value):
    temporary = path.with_name(path.name + ".tmp")
    if path.is_symlink() or temporary.is_symlink():
        raise ValueError(f"更新状态文件包含符号链接：{path.name}")
    with temporary.open("w", encoding="utf-8") as output:
        output.write(json.dumps(value, ensure_ascii=False))
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(path)
    _sync_directory(path.parent)


def _sync_directory(path):
    if os.name != "nt":
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _sync_directory_chain(path, stop):
    current = pathlib.Path(path)
    stop = pathlib.Path(stop)
    while current == stop or current.is_relative_to(stop):
        _sync_directory(current)
        if current == stop:
            return
        current = current.parent


def _write_file_atomically(path, contents):
    temporary = path.with_name(path.name + ".update-tmp")
    if path.is_symlink() or temporary.is_symlink():
        raise ValueError(f"更新路径包含符号链接：{path.name}")
    with temporary.open("wb") as output:
        output.write(contents)
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(path)
    _sync_directory(path.parent)


def _write_bytes_durably(path, contents):
    with path.open("wb") as output:
        output.write(contents)
        output.flush()
        os.fsync(output.fileno())


def read_update_failure(base_dir):
    runtime = pathlib.Path(base_dir) / ".runtime"
    path = runtime / "update-failure.json"
    if runtime.is_symlink() or path.is_symlink():
        raise ValueError("上次更新失败状态路径不安全，无法启动")
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise ValueError("上次更新失败状态文件损坏，无法安全启动") from error
    if (not isinstance(value, dict) or type(value.get("schema_version")) is not int
            or value.get("schema_version") != 1):
        raise ValueError("上次更新失败状态文件无效，无法安全启动")
    message = value.get("message")
    if not isinstance(message, str) or not message or len(message) > 500:
        raise ValueError("上次更新失败状态文件无效，无法安全启动")
    return message


def _write_update_failure(base_dir, message):
    runtime = pathlib.Path(base_dir) / ".runtime"
    if runtime.is_symlink():
        raise ValueError("更新运行目录不能是符号链接")
    runtime.mkdir(parents=True, exist_ok=True)
    _write_json_atomically(runtime / "update-failure.json", {
        "schema_version": 1, "message": message[:500],
    })


def _recover_release_transaction(base_dir):
    base_dir = pathlib.Path(base_dir).resolve()
    runtime = base_dir / ".runtime"
    journal_path = runtime / "update-transaction.json"
    if runtime.is_symlink() or journal_path.is_symlink():
        raise ValueError("更新事务路径不安全，已阻止启动")
    if not journal_path.exists():
        return
    try:
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise ValueError("发现损坏的更新事务记录，已阻止启动") from error
    stage_name = journal.get("stage") if isinstance(journal, dict) else None
    entries = journal.get("files") if isinstance(journal, dict) else None
    if (
        not isinstance(journal, dict)
        or type(journal.get("schema_version")) is not int
        or journal.get("schema_version") != 1
        or not isinstance(stage_name, str)
        or pathlib.Path(stage_name).name != stage_name
        or stage_name in {"", ".", ".."}
        or not isinstance(entries, dict)
    ):
        raise ValueError("发现无效的更新事务记录，已阻止启动")
    stage = runtime / stage_name
    if (runtime.is_symlink() or stage.is_symlink()
            or stage.parent.resolve() != runtime.resolve()):
        raise ValueError("更新事务备份目录不安全，已阻止启动")
    backup_root = stage / "rollback"
    if backup_root.is_symlink():
        raise ValueError("更新事务备份目录不安全，已阻止启动")
    dependencies_pending = journal.get("dependencies_pending")
    if not isinstance(dependencies_pending, bool):
        raise ValueError("更新事务记录无效，已阻止启动")
    for name, existed in entries.items():
        if (not isinstance(name, str)
                or (name != "release-manifest.json" and not _safe_name(name))):
            raise ValueError("更新事务包含不安全路径，已阻止启动")
        if not isinstance(existed, bool):
            raise ValueError("更新事务记录无效，已阻止启动")
        target = base_dir / name
        if target.is_symlink() or any(
            (base_dir / pathlib.Path(*pathlib.PurePosixPath(name).parts[:index])).is_symlink()
            for index in range(1, len(pathlib.PurePosixPath(name).parts))
        ):
            raise ValueError(f"更新恢复路径包含符号链接：{name}")
        if existed:
            backup = backup_root / name
            parent = backup.parent
            while parent != backup_root:
                if parent.is_symlink() or not parent.is_relative_to(backup_root):
                    raise ValueError("更新事务备份路径不安全，已阻止启动")
                parent = parent.parent
            if backup.is_symlink() or not backup.is_file():
                raise ValueError(f"更新恢复文件缺失：{name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            _write_file_atomically(target, backup.read_bytes())
        else:
            if target.exists():
                if not target.is_file():
                    raise ValueError(f"更新恢复目标不是文件：{name}")
                target.unlink()
                _sync_directory(target.parent)
    journal_path.unlink()
    _sync_directory(runtime)
    if dependencies_pending:
        _write_update_failure(
            base_dir,
            "上次更新在修改依赖环境期间中断；请重试更新以修复程序和依赖后再使用。",
        )
    shutil.rmtree(stage)


def recover_incomplete_update(base_dir):
    _recover_release_transaction(base_dir)


def _install_dependencies(base_dir):
    base_dir = pathlib.Path(base_dir).resolve()
    active_venv = pathlib.Path(sys.prefix).resolve()
    supported_venvs = (base_dir / ".venv", base_dir.parent.parent / ".venv")
    if not any(active_venv == candidate.resolve() for candidate in supported_venvs):
        raise ValueError("依赖已变化，但客户端未使用受支持的 .venv；请手动安装依赖")
    if sys.platform == "win32":
        if active_venv != (base_dir / ".venv").resolve():
            raise ValueError("Windows 自动安装要求使用客户端目录下的 .venv")
        subprocess.run(
            ["powershell.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", str(base_dir / "install.ps1"), "-NoShortcut"],
            cwd=base_dir, check=True, timeout=900,
        )
    else:
        venv_python = active_venv / "bin/python3"
        if not venv_python.is_file():
            raise ValueError("依赖已变化，但未找到当前 .venv 的 Python；请手动安装依赖")
        subprocess.run(
            [str(venv_python), "-m", "pip", "install", "-r", str(base_dir / "requirements.txt")],
            cwd=base_dir, check=True, timeout=900,
        )


def _apply_release(base_dir, stage, offer):
    archive_path = stage / "release.zip"
    if archive_path.stat().st_size != offer["size"]:
        raise ValueError("暂存发布包的大小已变化")
    if offer["digest"] and "sha256:" + hashlib.sha256(archive_path.read_bytes()).hexdigest() != offer["digest"]:
        raise ValueError("暂存发布包的 SHA-256 已变化")
    files, manifest = _validate_archive(archive_path, offer["tag"])
    has_manifest = (base_dir / "release-manifest.json").exists()
    previous = _check_local_files(base_dir)
    names = set(files) | (previous - set(files)) | {"release-manifest.json"}
    backups = {}
    for name in names:
        target = base_dir / name
        if target.is_symlink() or any(
            (base_dir / pathlib.Path(*pathlib.PurePosixPath(name).parts[:index])).is_symlink()
            for index in range(1, len(pathlib.PurePosixPath(name).parts))
        ):
            raise ValueError(f"更新路径包含符号链接：{name}")
        if target.exists():
            if not target.is_file():
                raise ValueError(f"更新路径不是文件：{name}")
            if has_manifest and name in files and name not in previous:
                raise ValueError(f"新版本文件与本地个人文件重名：{name}")
            backups[name] = target.read_bytes()
    old_requirements = backups.get("requirements.txt")
    runtime = base_dir / ".runtime"
    if runtime.is_symlink():
        raise ValueError("更新运行目录不能是符号链接")
    runtime.mkdir(parents=True, exist_ok=True)
    backup_root = stage / "rollback"
    backup_root.mkdir(parents=True, exist_ok=True)
    _sync_directory_chain(backup_root, runtime)
    transaction = {
        "schema_version": 1,
        "stage": stage.name,
        "dependencies_pending": False,
        "files": {},
    }
    for name in names:
        existed = name in backups
        transaction["files"][name] = existed
        if existed:
            backup = backup_root / name
            backup.parent.mkdir(parents=True, exist_ok=True)
            _write_bytes_durably(backup, backups[name])
            _sync_directory_chain(backup.parent, runtime)
    journal_path = runtime / "update-transaction.json"
    _write_json_atomically(journal_path, transaction)
    try:
        for name, contents in {**files, "release-manifest.json": json.dumps(
            manifest, ensure_ascii=False, indent=2,
        ).encode("utf-8") + b"\n"}.items():
            target = base_dir / name
            target.parent.mkdir(parents=True, exist_ok=True)
            _sync_directory_chain(target.parent, base_dir)
            _write_file_atomically(target, contents)
        for name in previous - set(files):
            target = base_dir / name
            target.unlink(missing_ok=True)
            _sync_directory(target.parent)
        if old_requirements != files.get("requirements.txt") or offer.get("force_dependencies"):
            transaction["dependencies_pending"] = True
            _write_json_atomically(journal_path, transaction)
            _install_dependencies(base_dir)
        version = _version_from_source((base_dir / "version.py").read_text(encoding="utf-8"))
        if version != manifest["version"]:
            raise ValueError("安装后的客户端版本与已验证发布包不一致")
        minimum = offer.get("minimum_version")
        if minimum is not None and _version_tuple(version) < _version_tuple(minimum):
            raise ValueError("安装后的版本低于官方最低支持版本")
        journal_path.unlink()
        _sync_directory(runtime)
    except Exception:
        _recover_release_transaction(base_dir)
        raise


def _apply_git(base_dir, offer):
    root = pathlib.Path(offer["root"])
    old_commit = _git(root, "rev-parse", "HEAD")
    target = offer["commit"]
    if _git(root, "status", "--porcelain", "--untracked-files=no"):
        raise ValueError("仓库在检查后发生修改，已取消更新")
    if subprocess.run(["git", "merge-base", "--is-ancestor", old_commit, target],
                      cwd=root).returncode != 0:
        raise ValueError("上游提交已不再是当前分支的快进目标")
    target_version = _version_from_source(
        _git(root, "show", f"{target}:client/data-entry/version.py")
    )
    if target_version != offer["version"]:
        raise ValueError("Git 更新目标版本与检查结果不一致")
    minimum = offer.get("minimum_version")
    if minimum is not None and _version_tuple(target_version) < _version_tuple(minimum):
        raise ValueError("Git 更新目标版本低于官方最低支持版本")
    _git(root, "merge", "--ff-only", target)
    installed_version = _version_from_source(
        (base_dir / "version.py").read_text(encoding="utf-8")
    )
    if installed_version != target_version:
        _git(root, "reset", "--hard", old_commit)
        raise ValueError("Git 更新后的客户端版本与目标版本不一致")
    if offer["requirements_changed"] or offer.get("force_dependencies"):
        try:
            _install_dependencies(base_dir)
        except Exception:
            if (_git(root, "rev-parse", "HEAD") == target
                    and not _git(root, "status", "--porcelain", "--untracked-files=no")):
                _git(root, "reset", "--hard", old_commit)
            raise


def _run_helper(plan_path):
    stage = plan_path.parent
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    base_dir = pathlib.Path(plan["base_dir"])
    offer = plan["offer"]
    _write_update_failure(base_dir, "更新尚未完成，请重试更新后再使用客户端。")
    try:
        _wait_for_exit(plan["parent_pid"])
        if offer["mode"] == "release":
            _apply_release(base_dir, stage, offer)
        else:
            _apply_git(base_dir, offer)
        (base_dir / ".runtime" / "update-failure.json").unlink(missing_ok=True)
        print(f"更新至 {offer['version']} 成功，正在重启客户端。", flush=True)
    except Exception as error:
        traceback.print_exc()
        _write_update_failure(
            base_dir,
            f"更新失败：{error}。请在门禁窗口重试；若依赖安装曾中断，重试会重新修复依赖。",
        )
        try:
            _recover_release_transaction(base_dir)
        except Exception:
            traceback.print_exc()
        print("更新失败，客户端将以受限门禁模式重启。", flush=True)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    os.execv(plan["executable"], [plan["executable"], *plan["argv"]])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=pathlib.Path, required=True)
    args = parser.parse_args()
    _run_helper(args.plan)


if __name__ == "__main__":
    main()
