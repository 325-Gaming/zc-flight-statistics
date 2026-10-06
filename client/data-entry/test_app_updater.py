"""Exercise release validation, local preservation, and Git fast-forward updates."""

import hashlib
import json
import pathlib
import subprocess
import tempfile
import unittest
import zipfile
from unittest.mock import patch

import app_updater


def _archive(path, version, files):
    manifest = {
        "schema_version": 1,
        "version": version,
        "tag": f"data-entry/v{version}",
        "commit": "a" * 40,
        "files": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()},
    }
    with zipfile.ZipFile(path, "w") as output:
        for name, data in files.items():
            output.writestr(name, data)
        output.writestr("release-manifest.json", json.dumps(manifest))
    return manifest


class AppUpdaterTests(unittest.TestCase):
    def test_windows_helper_starts_without_extra_console(self):
        with tempfile.TemporaryDirectory() as directory:
            base = pathlib.Path(directory)
            offer = {
                "mode": "release", "tag": "data-entry/v2.2.0",
                "version": "2.2.0", "minimum_version": "2.2.0",
            }
            with patch.object(app_updater.sys, "platform", "win32"), \
                 patch.object(app_updater.subprocess, "CREATE_NO_WINDOW", 0x08000000, create=True), \
                 patch.object(app_updater, "_download_release"), \
                 patch.object(app_updater.subprocess, "Popen") as popen:
                app_updater.start_update(base, offer, 123, ["webview_app.py"])
            self.assertEqual(popen.call_args.kwargs["creationflags"], 0x08000000)

    def test_dependency_install_uses_active_repository_venv(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            base = root / "client/data-entry"
            base.mkdir(parents=True)
            venv = root / ".venv"
            python = venv / "bin/python3"
            python.parent.mkdir(parents=True)
            python.touch()
            with patch.object(app_updater.sys, "prefix", str(venv)), \
                 patch.object(app_updater.subprocess, "run") as run:
                app_updater._install_dependencies(base)
            self.assertEqual(run.call_args.args[0][:4],
                             [str(python.resolve()), "-m", "pip", "install"])

    def test_dependency_install_rejects_unmanaged_python(self):
        with tempfile.TemporaryDirectory() as directory:
            base = pathlib.Path(directory) / "client/data-entry"
            base.mkdir(parents=True)
            with patch.object(app_updater.sys, "prefix", str(base.parent.parent / "other-venv")), \
                 patch.object(app_updater.subprocess, "run") as run:
                with self.assertRaisesRegex(ValueError, "未使用受支持的 .venv"):
                    app_updater._install_dependencies(base)
            run.assert_not_called()

    def test_release_list_selects_highest_stable_data_entry_version(self):
        def release(tag, prerelease=False):
            version = tag.removeprefix("data-entry/v")
            return {
                "tag_name": tag, "draft": False, "prerelease": prerelease,
                "assets": [{"name": f"data-entry-v{version}.zip", "state": "uploaded",
                            "size": 123, "digest": "sha256:" + "a" * 64,
                            "browser_download_url":
                            f"https://github.com/{app_updater.REPOSITORY}/releases/download/{tag.replace('/', '%2F')}/data-entry-v{version}.zip"}],
            }

        releases = [
            release("data-entry/v2.3.0", prerelease=True), release("v9.0.0"),
            release("data-entry/v2.2.0"), release("data-entry/v2.10.0"),
        ]
        with patch.object(app_updater, "_release_data", return_value=releases):
            offer = app_updater._check_release("2.1.0")
        self.assertEqual(offer["version"], "2.10.0")
        self.assertEqual(offer["mode"], "release")

    def test_archive_rejects_unsafe_path_and_bad_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = pathlib.Path(directory) / "release.zip"
            version = b'__version__ = "2.2.0"\n'
            _archive(archive, "2.2.0", {"version.py": version, "../bad.py": b"bad"})
            with self.assertRaisesRegex(ValueError, "不安全路径"):
                app_updater._validate_archive(archive, "data-entry/v2.2.0")
            _archive(archive, "2.2.0", {"version.py": version})
            with zipfile.ZipFile(archive, "a") as output:
                output.writestr("unlisted.py", "unexpected")
            with self.assertRaisesRegex(ValueError, "文件与清单不一致"):
                app_updater._validate_archive(archive, "data-entry/v2.2.0")

    def test_archive_rejects_program_file_checksum_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = pathlib.Path(directory) / "release.zip"
            contents = b'__version__ = "2.2.0"\n'
            manifest = _archive(archive, "2.2.0", {"version.py": contents})
            manifest["files"]["version.py"] = "0" * 64
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("version.py", contents)
                output.writestr("release-manifest.json", json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "文件校验失败"):
                app_updater._validate_archive(archive, "data-entry/v2.2.0")

    def test_download_rejects_release_asset_checksum_mismatch(self):
        class Response:
            status_code = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            @staticmethod
            def raise_for_status():
                return None

            def iter_bytes(self):
                yield self.body

        with tempfile.TemporaryDirectory() as directory:
            archive = pathlib.Path(directory) / "release.zip"
            _archive(archive, "2.2.0", {
                "version.py": b'__version__ = "2.2.0"\n',
            })
            response = Response()
            response.body = archive.read_bytes()
            offer = {
                "url": "https://github.com/325-Gaming/zc-flight-statistics/releases/download/"
                       "data-entry%2Fv2.2.0/data-entry-v2.2.0.zip",
                "size": archive.stat().st_size,
                "digest": "sha256:" + "0" * 64,
                "tag": "data-entry/v2.2.0",
            }
            with patch("httpx.stream", return_value=response):
                with self.assertRaisesRegex(ValueError, "SHA-256"):
                    app_updater._download_release(offer, pathlib.Path(directory) / "download.zip")

    def test_archive_rejects_case_variants_of_personal_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = pathlib.Path(directory) / "release.zip"
            version = b'__version__ = "2.2.0"\n'
            for path in ("CONFIG.JSON", ".ENV", ".VENV/bin/python3", ".Git/config"):
                with self.subTest(path=path):
                    _archive(archive, "2.2.0", {"version.py": version, path: b"bad"})
                    with self.assertRaisesRegex(ValueError, "不安全路径"):
                        app_updater._validate_archive(archive, "data-entry/v2.2.0")

    def test_release_update_preserves_personal_files_and_removes_obsolete_code(self):
        with tempfile.TemporaryDirectory() as directory:
            base = pathlib.Path(directory) / "data-entry"
            stage = base / ".runtime" / "stage"
            stage.mkdir(parents=True)
            old_files = {"version.py": b'__version__ = "2.1.0"\n',
                         "obsolete.py": b"obsolete", "requirements.txt": b"httpx\n",
                         "models/.gitkeep": b""}
            for name, contents in old_files.items():
                target = base / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(contents)
            old_manifest = _archive(stage / "old.zip", "2.1.0", old_files)
            (base / "release-manifest.json").write_text(json.dumps(old_manifest))
            (base / "config.json").write_text('{"personal": true}')
            (base / "models" / "model.onnx").write_bytes(b"personal model")
            new_files = {"version.py": b'__version__ = "2.2.0"\n',
                         "new.py": b"new", "requirements.txt": b"httpx\n",
                         "models/.gitkeep": b""}
            _archive(stage / "release.zip", "2.2.0", new_files)
            offer = {"tag": "data-entry/v2.2.0", "size": (stage / "release.zip").stat().st_size,
                     "digest": None}
            with patch.object(app_updater, "_install_dependencies") as install:
                app_updater._apply_release(base, stage, offer)
            install.assert_not_called()
            self.assertFalse((base / "obsolete.py").exists())
            self.assertEqual((base / "new.py").read_bytes(), b"new")
            self.assertEqual((base / "config.json").read_text(), '{"personal": true}')
            self.assertEqual((base / "models" / "model.onnx").read_bytes(), b"personal model")

    def test_release_update_rolls_back_on_dependency_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            base = pathlib.Path(directory)
            stage = base / ".runtime" / "stage"
            stage.mkdir(parents=True)
            old_files = {"version.py": b'__version__ = "2.1.0"\n',
                         "requirements.txt": b"httpx\n"}
            for name, contents in old_files.items():
                (base / name).write_bytes(contents)
            manifest = _archive(stage / "old.zip", "2.1.0", old_files)
            (base / "release-manifest.json").write_text(json.dumps(manifest))
            new_files = {"version.py": b'__version__ = "2.2.0"\n',
                         "requirements.txt": b"httpx\nmss\n"}
            _archive(stage / "release.zip", "2.2.0", new_files)
            offer = {"tag": "data-entry/v2.2.0", "size": (stage / "release.zip").stat().st_size,
                     "digest": None}
            with patch.object(app_updater, "_install_dependencies", side_effect=RuntimeError("offline")):
                with self.assertRaisesRegex(RuntimeError, "offline"):
                    app_updater._apply_release(base, stage, offer)
            self.assertEqual((base / "version.py").read_bytes(), old_files["version.py"])
            self.assertEqual((base / "requirements.txt").read_bytes(), old_files["requirements.txt"])
            self.assertEqual(json.loads((base / "release-manifest.json").read_text()), manifest)
            self.assertTrue((base / ".runtime/update-failure.json").exists())

    def test_helper_restarts_after_installing_verified_release(self):
        with tempfile.TemporaryDirectory() as directory:
            base = pathlib.Path(directory) / "data-entry"
            stage = base / ".runtime" / "update-test"
            stage.mkdir(parents=True)
            (base / "version.py").write_text('__version__ = "2.1.0"\n')
            (base / "requirements.txt").write_text("httpx\n")
            files = {"version.py": b'__version__ = "2.2.0"\n',
                     "requirements.txt": b"httpx\n"}
            archive = stage / "release.zip"
            _archive(archive, "2.2.0", files)
            plan = {
                "base_dir": str(base), "parent_pid": 123,
                "offer": {"mode": "release", "tag": "data-entry/v2.2.0",
                          "version": "2.2.0", "size": archive.stat().st_size, "digest": None},
                "executable": "/test/python", "argv": [str(base / "webview_app.py")],
            }
            plan_path = stage / "plan.json"
            plan_path.write_text(json.dumps(plan))
            with patch.object(app_updater, "_wait_for_exit") as wait, \
                 patch.object(app_updater.os, "execv") as restart:
                app_updater._run_helper(plan_path)
            wait.assert_called_once_with(123)
            restart.assert_called_once_with("/test/python", ["/test/python", str(base / "webview_app.py")])
            self.assertEqual((base / "version.py").read_bytes(), files["version.py"])
            self.assertFalse(stage.exists())

    def test_git_update_fast_forwards_and_keeps_untracked_file(self):
        def git(root, *args):
            return subprocess.run(["git", *args], cwd=root, check=True,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.decode().strip()

        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            remote = root / "remote.git"
            source = root / "source"
            installed = root / "installed"
            subprocess.run(["git", "init", "--bare", str(remote)], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["git", "clone", str(remote), str(source)], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            base = source / "client/data-entry"
            base.mkdir(parents=True)
            (base / "version.py").write_text('__version__ = "2.1.0"\n')
            (base / "requirements.txt").write_text("httpx\n")
            git(source, "add", "--", "client/data-entry")
            git(source, "-c", "commit.gpgsign=false", "-c", "user.name=Test", "-c", "user.email=test@example.com",
                "commit", "-m", "initial")
            git(source, "push", "-u", "origin", "HEAD")
            subprocess.run(["git", "clone", str(remote), str(installed)], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            (installed / "client/data-entry/output.txt").write_text("personal")
            (base / "version.py").write_text('__version__ = "2.2.0"\n')
            git(source, "add", "--", "client/data-entry/version.py")
            git(source, "-c", "commit.gpgsign=false", "-c", "user.name=Test", "-c", "user.email=test@example.com",
                "commit", "-m", "update")
            git(source, "push", "origin", "HEAD")
            offer = app_updater.check_update(installed / "client/data-entry", "2.1.0")
            self.assertTrue(offer["available"])
            self.assertEqual(offer["mode"], "git")
            (installed / "client/data-entry/version.py").write_text("local edit")
            with self.assertRaisesRegex(ValueError, "检查后发生修改"):
                app_updater._apply_git(installed / "client/data-entry", offer)
            (installed / "client/data-entry/version.py").write_text('__version__ = "2.1.0"\n')
            app_updater._apply_git(installed / "client/data-entry", offer)
            self.assertEqual((installed / "client/data-entry/version.py").read_text(),
                             '__version__ = "2.2.0"\n')
            self.assertEqual((installed / "client/data-entry/output.txt").read_text(), "personal")

            (base / "requirements.txt").write_text("httpx\nmss\n")
            git(source, "add", "--", "client/data-entry/requirements.txt")
            git(source, "-c", "commit.gpgsign=false", "-c", "user.name=Test", "-c", "user.email=test@example.com",
                "commit", "-m", "dependency update")
            git(source, "push", "origin", "HEAD")
            offer = app_updater.check_update(installed / "client/data-entry", "2.2.0")
            self.assertTrue(offer["requirements_changed"])
            before = git(installed, "rev-parse", "HEAD")
            with patch.object(app_updater, "_install_dependencies", side_effect=RuntimeError("offline")):
                with self.assertRaisesRegex(RuntimeError, "offline"):
                    app_updater._apply_git(installed / "client/data-entry", offer)
            self.assertEqual(git(installed, "rev-parse", "HEAD"), before)
            self.assertEqual((installed / "client/data-entry/output.txt").read_text(), "personal")

    def test_installation_detection_supports_worktree_and_release_zip(self):
        def git(root, *args):
            return subprocess.run(
                ["git", *args], cwd=root, check=True, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            ).stdout.decode().strip()

        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory) / "repo"
            root.mkdir()
            subprocess.run(["git", "init", "-b", "master", str(root)], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            git(root, "config", "user.name", "Test")
            git(root, "config", "user.email", "test@example.com")
            base = root / "client/data-entry"
            base.mkdir(parents=True)
            (base / "version.py").write_text('__version__ = "2.2.0"\n')
            git(root, "add", "client/data-entry/version.py")
            git(root, "commit", "-m", "initial")
            self.assertEqual(app_updater._git_root(base), root.resolve())

            worktree = pathlib.Path(directory) / "worktree"
            subprocess.run(["git", "-C", str(root), "worktree", "add", "-b", "linked",
                            str(worktree)], check=True, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
            worktree_base = worktree / "client/data-entry"
            self.assertTrue((worktree / ".git").is_file())
            self.assertEqual(app_updater._git_root(worktree_base), worktree.resolve())

            zipped = pathlib.Path(directory) / "unzipped/client/data-entry"
            zipped.mkdir(parents=True)
            self.assertIsNone(app_updater._git_root(zipped))
            with patch.object(app_updater, "_check_release") as release:
                app_updater.check_update(zipped, "2.2.0")
            release.assert_called_once_with("2.2.0")

    def test_interrupted_release_transaction_restores_files_and_blocks_partial_dependencies(self):
        with tempfile.TemporaryDirectory() as directory:
            base = pathlib.Path(directory)
            runtime = base / ".runtime"
            stage = runtime / "update-interrupted"
            (stage / "rollback").mkdir(parents=True)
            (stage / "rollback/version.py").write_text('__version__ = "2.2.0"\n')
            (base / "version.py").write_text('__version__ = "2.3.0"\n')
            (runtime / "update-transaction.json").write_text(json.dumps({
                "schema_version": 1,
                "stage": stage.name,
                "dependencies_pending": True,
                "files": {"version.py": True, "generated.py": False},
            }))
            (base / "generated.py").write_text("partial")

            app_updater.recover_incomplete_update(base)

            self.assertEqual((base / "version.py").read_text(), '__version__ = "2.2.0"\n')
            self.assertFalse((base / "generated.py").exists())
            self.assertFalse((runtime / "update-transaction.json").exists())
            self.assertIn("依赖环境", app_updater.read_update_failure(base))


if __name__ == "__main__":
    unittest.main()
