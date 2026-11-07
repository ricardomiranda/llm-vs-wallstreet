#!/usr/bin/env python3
"""Reject staged user financial data and common secret files."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

ALLOWED_LOCAL_PLACEHOLDERS: frozenset[str] = frozenset(
    {"references/.gitkeep", "output/.gitkeep"}
)
SENSITIVE_SUFFIXES: tuple[str, ...] = (
    ".xlsx",
    ".xls",
    ".csv",
    ".tsv",
    ".sqlite",
    ".sqlite3",
    ".db",
    ".pem",
    ".p12",
    ".pfx",
    ".key",
    ".crt",
)
SENSITIVE_NAMES: frozenset[str] = frozenset(
    {
        "id_rsa",
        "id_ed25519",
        "credentials.json",
        "secrets.toml",
        "aws_credentials",
        "token.json",
    }
)
SENSITIVE_CONTENT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----", re.IGNORECASE),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{30,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bsk-ant-[A-Za-z0-9_-]{32,}\b"),
    re.compile(r"\bU[0-9]{8}\b"),
    re.compile(
        r"(?i)\b(?:api[_-]?key|access[_-]?token|client[_-]?secret|password)"
        r"\s*[:=]\s*['\"]?[A-Za-z0-9/+=._-]{16,}"
    ),
)


def staged_paths(root: Path | None = None) -> list[str]:
    """Return staged paths, preserving filenames containing whitespace."""
    completed: subprocess.CompletedProcess[bytes] = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"],
        check=True,
        cwd=root,
        capture_output=True,
    )
    return [path.decode("utf-8", errors="surrogateescape") for path in completed.stdout.split(b"\0") if path]


def tracked_paths(root: Path | None = None) -> list[str]:
    """Return all paths in the current Git index."""
    completed: subprocess.CompletedProcess[bytes] = subprocess.run(
        ["git", "ls-files", "-z"],
        check=True,
        cwd=root,
        capture_output=True,
    )
    return [path.decode("utf-8", errors="surrogateescape") for path in completed.stdout.split(b"\0") if path]


def is_forbidden_path(path: str) -> bool:
    """Return whether a staged path could contain local financial data or secrets."""
    normalized: str = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if normalized in ALLOWED_LOCAL_PLACEHOLDERS:
        return False
    if normalized.startswith(("references/", "output/")):
        return True

    basename: str = PurePosixPath(normalized).name.lower()
    if normalized == ".env.example":
        return False
    if normalized.startswith("tests/fixtures/") and basename.startswith("synthetic_"):
        return False
    if basename.endswith("_buy_plan.json"):
        return True
    if (
        basename in SENSITIVE_NAMES
        or basename.startswith(".env")
        or ("credential" in basename and basename.endswith(".json"))
        or ("token" in basename and basename.endswith(".json"))
    ):
        return True
    return basename.endswith(SENSITIVE_SUFFIXES)


def find_forbidden_paths(paths: list[str]) -> list[str]:
    """Return forbidden paths from a staged-file list."""
    return [path for path in paths if is_forbidden_path(path)]


def contains_sensitive_content(content: bytes) -> bool:
    """Detect high-confidence credential and brokerage-account patterns."""
    text: str = content.decode("utf-8", errors="ignore")
    if b"\x00" in content:
        return False
    return any(pattern.search(text) is not None for pattern in SENSITIVE_CONTENT_PATTERNS)


def staged_content_findings(paths: list[str], root: Path) -> list[str]:
    """Return staged text files with high-confidence credential/PII patterns."""
    findings: list[str] = []
    for path in paths:
        if is_forbidden_path(path) or path.startswith("tests/"):
            continue
        if not path.endswith((".md", ".mdc", ".json", ".jsonc", ".toml", ".yml", ".yaml", ".py", ".txt", ".cfg", ".ini", ".env")):
            continue
        completed: subprocess.CompletedProcess[bytes] = subprocess.run(
            ["git", "show", f":{path}"],
            check=False,
            cwd=root,
            capture_output=True,
        )
        if completed.returncode == 0 and contains_sensitive_content(completed.stdout):
            findings.append(path)
    return findings


def tracked_content_findings(paths: list[str], root: Path) -> list[str]:
    """Return tracked text files with high-confidence credential/PII patterns."""
    findings: list[str] = []
    for path in paths:
        if is_forbidden_path(path) or path.startswith("tests/"):
            continue
        if not path.endswith((".md", ".mdc", ".json", ".jsonc", ".toml", ".yml", ".yaml", ".py", ".txt", ".cfg", ".ini", ".env")):
            continue
        completed: subprocess.CompletedProcess[bytes] = subprocess.run(
            ["git", "show", f":{path}"],
            check=False,
            cwd=root,
            capture_output=True,
        )
        if completed.returncode == 0 and contains_sensitive_content(completed.stdout):
            findings.append(path)
    return findings


def main() -> int:
    """Fail if the Git index includes a protected local-data or secret path."""
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Reject tracked or staged local portfolio data and secret files."
    )
    parser.add_argument(
        "--tracked",
        action="store_true",
        help="check every tracked path instead of only staged paths",
    )
    args: argparse.Namespace = parser.parse_args()
    root: Path = Path(__file__).resolve().parents[1]
    paths: list[str] = tracked_paths(root) if args.tracked else staged_paths(root)
    forbidden: list[str] = find_forbidden_paths(paths)
    content_findings: list[str] = (
        tracked_content_findings(paths, root)
        if args.tracked
        else staged_content_findings(paths, root)
    )
    forbidden.extend(path for path in content_findings if path not in forbidden)
    if forbidden:
        print("Refusing tracked local data or secret files:", file=sys.stderr)
        for path in forbidden:
            print(f"  {path}", file=sys.stderr)
        return 1
    print("No staged local data or secret files found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
