"""Tests for strict JSON file validation."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from validate_json import validate_json_file


class ValidateJsonTests(unittest.TestCase):
    """Verify valid JSON passes and invalid JSON reports its parse location."""

    def test_valid_json_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path: Path = Path(directory) / "valid.json"
            path.write_text(json.dumps({"ok": True}), encoding="utf-8")
            self.assertIsNone(validate_json_file(path))

    def test_invalid_json_returns_filename_and_parser_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path: Path = Path(directory) / "invalid.json"
            path.write_text('{"ok": true,}', encoding="utf-8")
            error: str | None = validate_json_file(path)
            self.assertIsNotNone(error)
            self.assertIn("invalid.json", error or "")
            self.assertIn("line 1", error or "")

    def test_non_utf8_file_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path: Path = Path(directory) / "bad-encoding.json"
            path.write_bytes(b"\xff")
            error: str | None = validate_json_file(path)
            self.assertIsNotNone(error)
            self.assertIn("bad-encoding.json", error or "")

    def test_nonstandard_numeric_constants_are_rejected(self) -> None:
        for value in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory:
                path: Path = Path(directory) / "non-standard.json"
                path.write_text(f'{{"value": {value}}}', encoding="utf-8")
                self.assertIn("Invalid JSON constant", validate_json_file(path) or "")


if __name__ == "__main__":
    unittest.main()
