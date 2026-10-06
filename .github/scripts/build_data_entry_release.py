"""Build a data-entry release asset from one committed Git tag."""

import argparse
import ast
import hashlib
import json
import pathlib
import re
import subprocess
import sys
import zipfile


REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "client" / "data-entry"))

from app_updater import validate_update_policy, version_is_at_least


CLIENT_PREFIX = "client/data-entry/"
TAG_PATTERN = re.compile(r"data-entry/v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
REQUIRED_WEBVIEW_ASSETS = {
    "webview_ui/gate.html",
    "webview_ui/gate.css",
    "webview_ui/fonts/fusion-pixel.css",
    "webview_ui/fonts/fusion-pixel-12px-proportional-ja.otf.woff2",
    "webview_ui/fonts/fusion-pixel-12px-proportional-latin.otf.woff2",
    "webview_ui/fonts/fusion-pixel-12px-proportional-zh_hans.otf.woff2",
    "webview_ui/licenses/OFL.txt",
}
FONT_URL_PATTERN = re.compile(r"""url\(["']?([^)"']+\.woff2)["']?\)""")


def git(*arguments):
    return subprocess.run(
        ["git", *arguments], cwd=REPOSITORY_ROOT, check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout


def version_from_source(source):
    module = ast.parse(source, filename="version.py")
    for statement in module.body:
        if isinstance(statement, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__version__"
            for target in statement.targets
        ):
            if isinstance(statement.value, ast.Constant) and isinstance(statement.value.value, str):
                return statement.value.value
    raise ValueError("version.py must contain a literal __version__ string")


def validate_release_version(tag, minimum_supported_version):
    match = TAG_PATTERN.fullmatch(tag)
    if match is None:
        raise ValueError("Expected tag data-entry/vMAJOR.MINOR.PATCH")
    version = ".".join(match.groups())
    if not version_is_at_least(version, minimum_supported_version):
        raise ValueError("Release version must not be below the minimum supported policy version")
    return version


def tracked_files(tag):
    records = git("ls-tree", "-r", "-z", tag, "--", "client/data-entry").split(b"\0")
    for record in records:
        if not record:
            continue
        metadata, raw_path = record.split(b"\t", 1)
        mode, kind, object_id = metadata.decode("ascii").split(" ")
        path = raw_path.decode("utf-8")
        if not path.startswith(CLIENT_PREFIX):
            raise ValueError(f"Unexpected release path: {path}")
        relative_path = path.removeprefix(CLIENT_PREFIX)
        if (
            not relative_path or "\\" in relative_path
            or any(part in {"", ".", ".."} for part in relative_path.split("/"))
        ):
            raise ValueError(f"Unsafe release path: {path}")
        if kind != "blob" or mode not in {"100644", "100755"}:
            raise ValueError(f"Unsupported release entry: {path} ({mode} {kind})")
        if relative_path.startswith("test_") and relative_path.endswith(".py"):
            continue
        if relative_path == "release-manifest.json":
            raise ValueError("release-manifest.json is reserved for generated metadata")
        yield relative_path, object_id


def validate_webview_assets(files):
    missing = REQUIRED_WEBVIEW_ASSETS - files.keys()
    if missing:
        raise ValueError(f"Release is missing required WebView assets: {', '.join(sorted(missing))}")
    try:
        stylesheet = files["webview_ui/fonts/fusion-pixel.css"].decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("Fusion Pixel stylesheet must be UTF-8") from error
    font_urls = FONT_URL_PATTERN.findall(stylesheet)
    if not font_urls:
        raise ValueError("Fusion Pixel stylesheet does not reference local WOFF2 fonts")
    for url in font_urls:
        font_path = pathlib.PurePosixPath("webview_ui/fonts") / url
        if (
            url.startswith("/") or "\\" in url
            or any(part in {"", ".", ".."} for part in pathlib.PurePosixPath(url).parts)
            or font_path.as_posix() not in files
        ):
            raise ValueError(f"Fusion Pixel font URL is not packaged locally: {url}")


def write_entry(archive, name, contents):
    info = zipfile.ZipInfo(name, ZIP_TIMESTAMP)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    archive.writestr(info, contents)


def build(tag, output_path):
    policy = validate_update_policy((REPOSITORY_ROOT / "update-policy.json").read_bytes())
    version = validate_release_version(tag, policy["minimum_supported_version"])
    commit = git("rev-parse", f"{tag}^{{commit}}").decode("ascii").strip()
    files = sorted(tracked_files(tag))
    if not files:
        raise ValueError("The tag contains no data-entry files")
    objects = {name: git("cat-file", "blob", object_id) for name, object_id in files}
    if "version.py" not in objects:
        raise ValueError("The tag does not contain client/data-entry/version.py")
    validate_webview_assets(objects)
    if version_from_source(objects["version.py"]) != version:
        raise ValueError("Tag version does not match client/data-entry/version.py")
    manifest = {
        "schema_version": 1,
        "version": version,
        "tag": tag,
        "commit": commit,
        "files": {
            name: hashlib.sha256(contents).hexdigest()
            for name, contents in sorted(objects.items())
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w") as archive:
        for name, contents in sorted(objects.items()):
            write_entry(archive, name, contents)
        write_entry(
            archive, "release-manifest.json",
            (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        )
    with zipfile.ZipFile(output_path) as archive:
        if archive.testzip() is not None:
            raise ValueError("Release ZIP integrity check failed")
    print(f"Built {output_path} from {tag} ({commit[:12]})")
    print(f"SHA-256: {hashlib.sha256(output_path.read_bytes()).hexdigest()}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    args = parser.parse_args()
    build(args.tag, args.output)


if __name__ == "__main__":
    main()
