#!/usr/bin/env python3
"""opencode hook: block `git commit` when project mypy fails."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

Permission = dict[str, str]


def allow() -> Permission:
    return {"permission": "allow"}


def deny(message: str) -> Permission:
    return {
        "permission": "deny",
        "user_message": message,
        "agent_message": message,
    }


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def main() -> int:
    payload: dict[str, Any] = json.load(sys.stdin)
    command: str = str(payload.get("command") or "")
    if "git commit" not in command:
        json.dump(allow(), sys.stdout)
        return 0

    root: Path = repo_root()
    completed: subprocess.CompletedProcess[str] = subprocess.run(
        [sys.executable, str(root / "scripts" / "pre_commit.py")],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if completed.stdout:
        sys.stderr.write(completed.stdout)
    if completed.stderr:
        sys.stderr.write(completed.stderr)

    if completed.returncode != 0:
        json.dump(
            deny("pre-commit mypy failed. Fix type errors before committing."),
            sys.stdout,
        )
        return 0

    json.dump(allow(), sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
