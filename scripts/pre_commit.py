#!/usr/bin/env python3
"""Run required pre-commit checks. Invoked by the git and opencode pre-commit hooks."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_SCRIPTS_DIR: Path = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from project_env import ensure_venv, repo_root
from check_staged_files import find_forbidden_paths, staged_paths

SKIP_PREFIXES: tuple[str, ...] = (".opencode/", ".venv/")
PROJECT_PYTHON_PREFIXES: tuple[str, ...] = ("scripts/",)


def normalize(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def is_project_python(path: str) -> bool:
    normalized: str = normalize(path)
    if any(normalized.startswith(prefix) for prefix in SKIP_PREFIXES):
        return False
    if not normalized.endswith(".py"):
        return False
    if "/" not in normalized:
        return True
    return any(normalized.startswith(prefix) for prefix in PROJECT_PYTHON_PREFIXES)


def staged_project_python(root: Path) -> list[str]:
    listed: subprocess.CompletedProcess[str] = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        check=True,
        cwd=root,
        capture_output=True,
        text=True,
    )
    return [path for path in listed.stdout.splitlines() if is_project_python(path)]


def run_mypy(root: Path, python: Path) -> int:
    completed: subprocess.CompletedProcess[bytes] = subprocess.run(
        [str(python), "-m", "mypy"],
        cwd=root,
    )
    return completed.returncode


def main() -> int:
    root: Path = repo_root()
    forbidden: list[str] = find_forbidden_paths(staged_paths(root))
    if forbidden:
        print("pre-commit: refusing to stage local data or secret files:", file=sys.stderr)
        for path in forbidden:
            print(f"  {path}", file=sys.stderr)
        return 1

    staged: list[str] = staged_project_python(root)
    if not staged:
        print("pre-commit: skipping mypy (no project Python staged)")
        return 0

    python: Path = ensure_venv(root)
    print("pre-commit: running mypy on project Python")
    return run_mypy(root, python)


if __name__ == "__main__":
    raise SystemExit(main())
