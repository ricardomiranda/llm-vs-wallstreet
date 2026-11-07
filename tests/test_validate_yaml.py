"""Tests for tracked YAML syntax validation."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from validate_yaml import validate_yaml_file


class ValidateYamlTests(unittest.TestCase):
    """Verify YAML files are parsed safely and failures identify the source."""

    def test_valid_yaml_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path: Path = Path(directory) / "valid.yaml"
            path.write_text("name: workflow\njobs:\n  check:\n    runs-on: ubuntu-latest\n", encoding="utf-8")
            self.assertIsNone(validate_yaml_file(path))

    def test_invalid_yaml_reports_filename_and_parser_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path: Path = Path(directory) / "invalid.yml"
            path.write_text("name: workflow\njobs: [\n", encoding="utf-8")
            error: str | None = validate_yaml_file(path)
            self.assertIsNotNone(error)
            self.assertIn("invalid.yml", error or "")
            self.assertTrue("line" in (error or "").lower())

    def test_non_utf8_file_reports_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path: Path = Path(directory) / "bad-encoding.yaml"
            path.write_bytes(b"\xff")
            error: str | None = validate_yaml_file(path)
            self.assertIsNotNone(error)
            self.assertIn("bad-encoding.yaml", error or "")


if __name__ == "__main__":
    unittest.main()
