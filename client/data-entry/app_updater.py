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
TAG_PATTERN = re.compile(r"data-entry/v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")
MAX_ARCHIVE_SIZE = 100 * 1024 * 1024
MAX_UNPACKED_SIZE = 150 * 1024 * 1024
PROTECTED_NAMES = {".env", "config.json", "name.csv", "release-manifest.json"}
PROTECTED_ROOTS = {".git", ".runtime", ".venv", "models"}
WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{n}" for n in range(1, 10)),
                    *(f"LPT{n}" for n in range(1, 10))}


def _version_from_source(source):
    module = ast.parse(source, filename="version.py")
    for statement in module.body:
        if isinstance(statement, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__version__"
            for target in statement.targets
        ):
            if isinstance(statement.value, ast.Constant) and isinstance(statement.value.value, str):
                return statement.value.value
    raise ValueError("version.py 中没有有效的版本号")


def _version_tuple(version):
    match = re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", version)
    if match is None:
        raise ValueError("版本号格式无效")
    return tuple(map(int, match.groups()))


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
    if not (root / ".git").is_dir() or shutil.which("git") is None:
        return None
    try:
        actual = pathlib.Path(_git(root, "rev-parse", "--show-toplevel")).resolve()
    except (OSError, RuntimeError):
        return None
    return root if actual == root.resolve() else None


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


def _check_release(current_version):
    import httpx

    response = httpx.get(
        RELEASES_URL, headers={"Accept": "application/vnd.github+json"},
        follow_redirects=True, timeout=20,
    )
    response.raise_for_status()
    releases = response.json()
    if not isinstance(releases, list):
        raise ValueError("GitHub Release 返回的数据格式无效")
    candidates = []
    for release in releases:
        if not isinstance(release, dict) or release.get("draft") or release.get("prerelease"):
            continue
        tag = release.get("tag_name", "")
        match = TAG_PATTERN.fullmatch(tag) if isinstance(tag, str) else None
        if match is None:
            continue
        candidates.append((tuple(map(int, match.groups())), release))
    if not candidates or max(candidates, key=lambda item: item[0])[0] <= _version_tuple(current_version):
        return {"available": False, "mode": "release", "current_version": current_version}
    version_parts, release = max(candidates, key=lambda item: item[0])
    version = ".".join(map(str, version_parts))
    tag = release["tag_name"]
    filename = f"data-entry-v{version}.zip"
    asset = next((item for item in release.get("assets", [])
                  if isinstance(item, dict) and item.get("name") == filename), None)
    if asset is None or asset.get("state") != "uploaded":
        raise ValueError(f"新版 {version} 尚未提供 {filename}")
    url = asset.get("browser_download_url")
    parsed = urlsplit(url) if isinstance(url, str) else None
    if (parsed is None or parsed.scheme != "https" or parsed.netloc != "github.com"
            or parsed.query or parsed.fragment or
            unquote(parsed.path) != f"/{REPOSITORY}/releases/download/{tag}/{filename}"):
        raise ValueError("GitHub Release 下载地址无效")
    size = asset.get("size")
    if not isinstance(size, int) or not 0 < size <= MAX_ARCHIVE_SIZE:
        raise ValueError("GitHub Release 压缩包大小无效")
    digest = asset.get("digest")
    if digest is not None and not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ValueError("GitHub Release 文件校验值无效")
    return {
        "available": True, "mode": "release", "current_version": current_version,
        "version": version, "tag": tag, "url": url, "size": size, "digest": digest,
    }


def check_update(base_dir, current_version):
    base_dir = pathlib.Path(base_dir).resolve()
    if (base_dir.parent.parent / ".git").is_dir():
        if shutil.which("git") is None:
            raise ValueError("此安装属于 Git 仓库，但系统中没有可用的 git 命令")
        root = _git_root(base_dir)
        if root is None:
            raise ValueError("无法识别当前 Git 仓库，请检查仓库状态")
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
        if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
            raise ValueError("发布包清单格式无效")
        match = TAG_PATTERN.fullmatch(expected_tag)
        if (match is None or manifest.get("tag") != expected_tag
                or manifest.get("version") != ".".join(match.groups())):
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


def _download_release(offer, destination):
    import httpx

    digest = hashlib.sha256()
    count = 0
    with httpx.stream("GET", offer["url"], follow_redirects=True, timeout=90) as response:
        response.raise_for_status()
        with destination.open("wb") as output:
            for chunk in response.iter_bytes():
                count += len(chunk)
                if count > MAX_ARCHIVE_SIZE or count > offer["size"]:
                    raise ValueError("下载的发布包超出预期大小")
                digest.update(chunk)
                output.write(chunk)
    if count != offer["size"]:
        raise ValueError("下载的发布包大小与 GitHub Release 不一致")
    if offer["digest"] and digest.hexdigest() != offer["digest"].removeprefix("sha256:"):
        raise ValueError("下载的发布包 SHA-256 与 GitHub Release 不一致")
    _validate_archive(destination, offer["tag"])


def start_update(base_dir, offer, parent_pid, argv):
    base_dir = pathlib.Path(base_dir).resolve()
    runtime = base_dir / ".runtime"
    runtime.mkdir(exist_ok=True)
    stage = runtime / f"update-{uuid.uuid4().hex}"
    stage.mkdir()
    try:
        if offer["mode"] == "release":
            _download_release(offer, stage / "release.zip")
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
    if not manifest_path.exists():
        return set()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    hashes = manifest.get("files") if isinstance(manifest, dict) else None
    if not isinstance(hashes, dict):
        raise ValueError("现有安装清单无效")
    for name, expected in hashes.items():
        if not _safe_name(name) or not isinstance(expected, str):
            raise ValueError("现有安装清单包含不安全文件")
        target = base_dir / name
        if target.is_symlink() or (target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() != expected):
            raise ValueError(f"本地程序文件已修改，无法自动覆盖：{name}")
    return set(hashes)


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
    try:
        for name, contents in {**files, "release-manifest.json": json.dumps(
            manifest, ensure_ascii=False, indent=2,
        ).encode("utf-8") + b"\n"}.items():
            target = base_dir / name
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(target.name + ".update-tmp")
            try:
                temporary.write_bytes(contents)
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
        for name in previous - set(files):
            (base_dir / name).unlink(missing_ok=True)
        if old_requirements != files.get("requirements.txt"):
            _install_dependencies(base_dir)
    except Exception:
        for name in names:
            target = base_dir / name
            if name in backups:
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_name(target.name + ".update-rollback-tmp")
                try:
                    temporary.write_bytes(backups[name])
                    temporary.replace(target)
                finally:
                    temporary.unlink(missing_ok=True)
            else:
                target.unlink(missing_ok=True)
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
    _git(root, "merge", "--ff-only", target)
    if offer["requirements_changed"]:
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
    _wait_for_exit(plan["parent_pid"])
    try:
        if offer["mode"] == "release":
            _apply_release(base_dir, stage, offer)
        else:
            _apply_git(base_dir, offer)
        print(f"更新至 {offer['version']} 成功，正在重启客户端。", flush=True)
    except Exception:
        traceback.print_exc()
        print("更新失败；程序文件已尽可能恢复，正在重启原版客户端。", flush=True)
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
