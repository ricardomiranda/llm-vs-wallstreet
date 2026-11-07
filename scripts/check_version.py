#!/usr/bin/env python3
"""Validate that the project version is consistent and higher than a base version."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

SEMVER_PATTERN: re.Pattern[str] = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)
NUMERIC_IDENTIFIER_PATTERN: re.Pattern[str] = re.compile(r"^[0-9]+$")
LEADING_ZERO_PATTERN: re.Pattern[str] = re.compile(r"^0[0-9]+$")
README_VERSION_PATTERN: re.Pattern[str] = re.compile(r"^version `([^`]+)`\.$", re.MULTILINE)
CONFIG_VERSION_PATTERN: re.Pattern[str] = re.compile(
    r"^current_version\s*=\s*(\S+)\s*$", re.MULTILINE
)


@dataclass(frozen=True)
class SemanticVersion:
    """Parsed Semantic Version components."""

    major: int
    minor: int
    patch: int
    prerelease: tuple[str, ...]


def parse_semver(value: str) -> SemanticVersion:
    """Parse a valid SemVer string, rejecting invalid numeric identifiers."""
    match: re.Match[str] | None = SEMVER_PATTERN.fullmatch(value)
    if match is None:
        raise ValueError(f"Invalid Semantic Version: {value!r}")

    prerelease_value: str | None = match.group(4)
    prerelease: tuple[str, ...] = (
        tuple(prerelease_value.split(".")) if prerelease_value else ()
    )
    for identifier in prerelease:
        if NUMERIC_IDENTIFIER_PATTERN.fullmatch(identifier) and LEADING_ZERO_PATTERN.fullmatch(
            identifier
        ):
            raise ValueError(f"Invalid Semantic Version (numeric prerelease has leading zero): {value!r}")

    return SemanticVersion(
        major=int(match.group(1)),
        minor=int(match.group(2)),
        patch=int(match.group(3)),
        prerelease=prerelease,
    )


def compare_semver(left: SemanticVersion, right: SemanticVersion) -> int:
    """Compare SemVer precedence; build metadata does not affect precedence."""
    left_core: tuple[int, int, int] = (left.major, left.minor, left.patch)
    right_core: tuple[int, int, int] = (right.major, right.minor, right.patch)
    if left_core != right_core:
        return 1 if left_core > right_core else -1

    if not left.prerelease and not right.prerelease:
        return 0
    if not left.prerelease:
        return 1
    if not right.prerelease:
        return -1

    for left_identifier, right_identifier in zip(left.prerelease, right.prerelease):
        if left_identifier == right_identifier:
            continue
        left_numeric: bool = bool(NUMERIC_IDENTIFIER_PATTERN.fullmatch(left_identifier))
        right_numeric: bool = bool(NUMERIC_IDENTIFIER_PATTERN.fullmatch(right_identifier))
        if left_numeric and right_numeric:
            return 1 if int(left_identifier) > int(right_identifier) else -1
        if left_numeric != right_numeric:
            return -1 if left_numeric else 1
        return 1 if left_identifier > right_identifier else -1

    if len(left.prerelease) == len(right.prerelease):
        return 0
    return 1 if len(left.prerelease) > len(right.prerelease) else -1


def read_single_match(path: Path, pattern: re.Pattern[str], description: str) -> str:
    """Read a file and require exactly one captured version value."""
    matches: list[str] = pattern.findall(path.read_text(encoding="utf-8"))
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one {description} in {path.name}; found {len(matches)}")
    return matches[0]


def project_version(root: Path) -> str:
    """Read and validate the three synchronized project version declarations."""
    version_file: str = (root / "version.txt").read_text(encoding="utf-8").strip()
    readme_version: str = read_single_match(
        root / "README.md", README_VERSION_PATTERN, "README version"
    )
    config_version: str = read_single_match(
        root / ".bumpversion.cfg", CONFIG_VERSION_PATTERN, "configured version"
    )
    versions: set[str] = {version_file, readme_version, config_version}
    if len(versions) != 1:
        raise ValueError(
            "Version files disagree: "
            f"version.txt={version_file!r}, README.md={readme_version!r}, "
            f".bumpversion.cfg={config_version!r}"
        )
    parse_semver(version_file)
    return version_file


def validate_version_increase(root: Path, base_version_text: str) -> tuple[str, str]:
    """Require a valid, consistent project version with higher SemVer precedence."""
    base_version: SemanticVersion = parse_semver(base_version_text.strip())
    current_version_text: str = project_version(root)
    current_version: SemanticVersion = parse_semver(current_version_text)
    if compare_semver(current_version, base_version) <= 0:
        raise ValueError(
            f"Project version {current_version_text} must be greater than base version "
            f"{base_version_text.strip()}"
        )
    return base_version_text.strip(), current_version_text


def main(argv: list[str] | None = None) -> int:
    """Run the version check against the supplied base branch version."""
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Require a consistent project SemVer greater than the base version."
    )
    parser.add_argument("base_version", help="SemVer read from the pull request base branch")
    args: argparse.Namespace = parser.parse_args(argv)

    try:
        base_version: str
        current_version: str
        base_version, current_version = validate_version_increase(
            Path(__file__).resolve().parents[1], args.base_version
        )
    except (OSError, ValueError) as error:
        print(f"Version check failed: {error}", file=sys.stderr)
        return 1

    print(f"Version check passed: {current_version} is greater than {base_version}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
