"""Validate the repository's data-entry minimum-version policy."""

import pathlib
import sys


REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "client" / "data-entry"))

from app_updater import validate_update_policy


def main():
    validate_update_policy((REPOSITORY_ROOT / "update-policy.json").read_bytes())
    print("update-policy.json is valid")


if __name__ == "__main__":
    main()
