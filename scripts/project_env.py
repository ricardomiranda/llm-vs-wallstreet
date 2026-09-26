"""Shared helpers for running project tools inside `.venv`."""

from __future__ import annotations

import subprocess
import sys
import venv
from pathlib import Path

REQUIRED_MODULES: tuple[str, ...] = ("bumpversion", "mypy")


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
    missing: bool = any(not module_available(python, name) for name in REQUIRED_MODULES)
    if missing:
        subprocess.run(
            [str(python), "-m", "pip", "install", "-r", str(root / "requirements-dev.txt")],
            check=True,
            cwd=root,
        )
    return python


def running_in_venv(root: Path) -> bool:
    return Path(sys.prefix).resolve() == (root / ".venv").resolve()
