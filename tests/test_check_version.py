"""Tests for the pull-request Semantic Version increase check."""

from __future__ import annotations

import tempfile
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from check_version import (
    compare_semver,
    parse_semver,
    validate_version_increase,
)


class SemanticVersionTests(unittest.TestCase):
    """Verify SemVer parsing and precedence rules."""

    def test_release_is_greater_than_its_prerelease(self) -> None:
        self.assertGreater(compare_semver(parse_semver("1.0.0"), parse_semver("1.0.0-rc.1")), 0)

    def test_prerelease_identifiers_follow_semver_precedence(self) -> None:
        self.assertLess(compare_semver(parse_semver("1.0.0-rc.2"), parse_semver("1.0.0-rc.10")), 0)
        self.assertLess(compare_semver(parse_semver("1.0.0-1"), parse_semver("1.0.0-alpha")), 0)
        self.assertLess(compare_semver(parse_semver("1.0.0-alpha"), parse_semver("1.0.0-alpha.1")), 0)

    def test_build_metadata_does_not_increase_precedence(self) -> None:
        self.assertEqual(compare_semver(parse_semver("1.0.0+build.2"), parse_semver("1.0.0+build.1")), 0)

    def test_invalid_semver_is_rejected(self) -> None:
        for version in ("1.0", "01.0.0", "1.0.0-01", "v1.0.0"):
            with self.subTest(version=version), self.assertRaises(ValueError):
                parse_semver(version)


class ProjectVersionIncreaseTests(unittest.TestCase):
    """Verify synchronized version files and strict increase validation."""

    def create_project(self, root: Path, version: str) -> None:
        (root / "version.txt").write_text(f"{version}\n", encoding="utf-8")
        (root / "README.md").write_text(f"version `{version}`.\n", encoding="utf-8")
        (root / ".bumpversion.cfg").write_text(
            f"[bumpversion]\ncurrent_version = {version}\n", encoding="utf-8"
        )

    def test_higher_version_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root: Path = Path(directory)
            self.create_project(root, "1.2.4")
            self.assertEqual(validate_version_increase(root, "1.2.3"), ("1.2.3", "1.2.4"))

    def test_unchanged_or_lower_version_fails(self) -> None:
        for current_version in ("1.2.3", "1.2.2"):
            with self.subTest(current_version=current_version), tempfile.TemporaryDirectory() as directory:
                root: Path = Path(directory)
                self.create_project(root, current_version)
                with self.assertRaisesRegex(ValueError, "must be greater"):
                    validate_version_increase(root, "1.2.3")

    def test_inconsistent_version_files_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root: Path = Path(directory)
            self.create_project(root, "1.2.4")
            (root / "README.md").write_text("version `1.2.5`.\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Version files disagree"):
                validate_version_increase(root, "1.2.3")


if __name__ == "__main__":
    unittest.main()
