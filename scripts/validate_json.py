#!/usr/bin/env python3
"""Validate tracked strict JSON files in the Git index."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def reject_nonstandard_constant(value: str) -> None:
    """Reject Python JSON's non-standard NaN and infinity extensions."""
    raise ValueError(f"Invalid JSON constant: {value}")


def tracked_json_paths(root: Path) -> list[str]:
    """Return tracked JSON paths from the Git index, excluding JSONC."""
    completed: subprocess.CompletedProcess[bytes] = subprocess.run(
        ["git", "ls-files", "--cached", "-z", "--", "*.json"],
        check=True,
        cwd=root,
        capture_output=True,
    )
    return [
        path.decode("utf-8", errors="surrogateescape")
        for path in completed.stdout.split(b"\0")
        if path and not path.decode("utf-8", errors="surrogateescape").endswith(".jsonc")
    ]


def validate_json_file(path: Path) -> str | None:
    """Return a formatted parsing error, or None when the file is valid JSON."""
    try:
        with path.open("r", encoding="utf-8") as json_file:
            json.load(json_file, parse_constant=reject_nonstandard_constant)
    except (OSError, UnicodeError, ValueError) as error:
        return f"{path}: {error}"
    return None


def validate_tracked_json(root: Path) -> list[str]:
    """Validate every tracked JSON file and return all file-specific errors."""
    return [
        error
        for relative_path in tracked_json_paths(root)
        if (error := validate_json_file(root / relative_path)) is not None
    ]


def main() -> int:
    """Run validation and print errors with filenames."""
    root: Path = Path(__file__).resolve().parents[1]
    errors: list[str] = validate_tracked_json(root)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print("All tracked strict JSON files are valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
