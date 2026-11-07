#!/usr/bin/env python3
"""Validate tracked YAML files in the Git index."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml


def tracked_yaml_paths(root: Path) -> list[str]:
    """Return tracked .yml and .yaml paths from the Git index."""
    completed: subprocess.CompletedProcess[bytes] = subprocess.run(
        ["git", "ls-files", "--cached", "-z", "--", "*.yml", "*.yaml"],
        check=True,
        cwd=root,
        capture_output=True,
    )
    return [
        path.decode("utf-8", errors="surrogateescape")
        for path in completed.stdout.split(b"\0")
        if path
    ]


def validate_yaml_file(path: Path) -> str | None:
    """Return a filename-qualified YAML parse error, or None when valid."""
    try:
        with path.open("r", encoding="utf-8") as yaml_file:
            yaml.safe_load(yaml_file)
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        return f"{path}: {error}"
    return None


def validate_tracked_yaml(root: Path) -> list[str]:
    """Validate every tracked YAML file and return all file-specific errors."""
    return [
        error
        for relative_path in tracked_yaml_paths(root)
        if (error := validate_yaml_file(root / relative_path)) is not None
    ]


def main() -> int:
    """Run validation and print errors with filenames."""
    root: Path = Path(__file__).resolve().parents[1]
    errors: list[str] = validate_tracked_yaml(root)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print("All tracked YAML files are valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
