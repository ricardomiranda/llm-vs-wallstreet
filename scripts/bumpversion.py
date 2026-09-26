#!/usr/bin/env python3
"""Bump the project version with bumpversion, using the project venv."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import venv
from pathlib import Path

PARTS: tuple[str, ...] = ("major", "minor", "patch")


def repo_root() -> Path:
    here: Path = Path(__file__).resolve()
    candidate: Path
    for candidate in (here.parent, *here.parents):
        if (candidate / ".bumpversion.cfg").is_file():
            return candidate
    raise SystemExit("Could not find .bumpversion.cfg (not in the project repo?)")


def venv_python(root: Path) -> Path:
    return root / ".venv" / "bin" / "python"


def module_available(python: Path, name: str) -> bool:
    probe: subprocess.CompletedProcess[bytes] = subprocess.run(
        [str(python), "-c", f"import {name}"],
        check=False,
        capture_output=True,
    )
    return probe.returncode == 0


def ensure_pip(python: Path) -> None:
    if module_available(python, "pip"):
        return
    subprocess.run([str(python), "-m", "ensurepip", "--upgrade"], check=True)


def ensure_venv(root: Path) -> Path:
    python: Path = venv_python(root)
    env_dir: Path = root / ".venv"
    if not python.is_file():
        venv.EnvBuilder(with_pip=True).create(env_dir)
    ensure_pip(python)
    if not module_available(python, "bumpversion"):
        subprocess.run(
            [str(python), "-m", "pip", "install", "-r", str(root / "requirements-dev.txt")],
            check=True,
            cwd=root,
        )
    return python


def running_in_venv(root: Path) -> bool:
    return Path(sys.prefix).resolve() == (root / ".venv").resolve()


def current_version(root: Path) -> str:
    return (root / "version.txt").read_text(encoding="utf-8").strip()


def main(argv: list[str] | None = None) -> int:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Increment the project version with semantic versioning."
    )
    parser.add_argument(
        "part",
        choices=PARTS,
        help="Which part of MAJOR.MINOR.PATCH to increment",
    )
    parser.add_argument(
        "bumpversion_args",
        nargs=argparse.REMAINDER,
        help="Extra arguments forwarded to bumpversion (e.g. --dry-run)",
    )
    args: argparse.Namespace = parser.parse_args(argv)

    root: Path = repo_root()
    python: Path = ensure_venv(root)
    part: str = args.part
    forwarded: list[str] = list(args.bumpversion_args)

    if not running_in_venv(root):
        cmd: list[str] = [str(python), str(Path(__file__).resolve()), part, *forwarded]
        rerun: subprocess.CompletedProcess[bytes] = subprocess.run(cmd, cwd=root)
        return rerun.returncode

    before: str = current_version(root)
    extra: list[str] = [argument for argument in forwarded if argument != "--"]
    if "--allow-dirty" not in extra:
        extra.append("--allow-dirty")
    completed: subprocess.CompletedProcess[bytes] = subprocess.run(
        [str(python), "-m", "bumpversion", part, *extra],
        cwd=root,
    )
    if completed.returncode != 0:
        return completed.returncode

    after: str = current_version(root)
    if "--dry-run" in extra:
        print(f"Dry run: would bump {before} ({part})")
    else:
        print(f"Bumped version {before} -> {after} ({part})")
    return 0


if __name__ == "__main__":
    os.chdir(repo_root())
    raise SystemExit(main())
