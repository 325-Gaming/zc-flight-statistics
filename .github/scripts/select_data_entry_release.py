"""Select the newest unpublished data-entry tag newer than existing releases."""

import os
import re
import subprocess
import sys


TAG_PATTERN = re.compile(r"data-entry/v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")


def version(tag):
    match = TAG_PATTERN.fullmatch(tag)
    return tuple(map(int, match.groups())) if match else None


def select_tag(tags, releases):
    published = {tag for tag in releases if version(tag) is not None}
    last_published = max((version(tag) for tag in published), default=(-1, -1, -1))
    pending = [(version(tag), tag) for tag in tags
               if version(tag) is not None and version(tag) > last_published
               and tag not in published]
    return max(pending)[1] if pending else None


def run(*arguments):
    return subprocess.run(arguments, check=True, text=True,
                          stdout=subprocess.PIPE).stdout


def main():
    repository = os.environ["GITHUB_REPOSITORY"]
    remote = run("git", "ls-remote", "--tags", "--refs", "origin",
                 "refs/tags/data-entry/v*")
    tags = [line.split("\t", 1)[1].removeprefix("refs/tags/")
            for line in remote.splitlines()]
    released = run("gh", "api", "--paginate",
                   f"repos/{repository}/releases?per_page=100", "--jq", ".[].tag_name")
    selected = select_tag(tags, released.splitlines())
    if selected:
        print(f"tag={selected}")
        print(f"Selected {selected} for scheduled release.", file=sys.stderr)
    else:
        print("No newer unpublished data-entry tag found.", file=sys.stderr)


if __name__ == "__main__":
    main()
