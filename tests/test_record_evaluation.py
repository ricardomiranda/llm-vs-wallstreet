"""Tests for recording successful portfolio evaluation runs."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from record_evaluation import main, record_evaluation


class RecordEvaluationTests(unittest.TestCase):
    """Record timestamps only when a portfolio snapshot exists."""

    def test_records_and_updates_utc_completion_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "portfolio.sqlite3"
            with sqlite3.connect(database) as connection:
                connection.execute("CREATE TABLE snapshots(id INTEGER PRIMARY KEY)")
                connection.execute("INSERT INTO snapshots VALUES (1)")
            first = record_evaluation(database)
            second = record_evaluation(database)
            offset = datetime.fromisoformat(second).utcoffset()
            self.assertIsNotNone(offset)
            self.assertEqual(offset.total_seconds(), 0)  # type: ignore[union-attr]
            with sqlite3.connect(database) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM portfolio_evaluation_status").fetchone()[0], 1)
                self.assertEqual(connection.execute("SELECT completed_at FROM portfolio_evaluation_status").fetchone()[0], second)
            self.assertGreaterEqual(second, first)

    def test_requires_existing_database_and_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.sqlite3"
            with self.assertRaises(FileNotFoundError):
                record_evaluation(missing)
            database = Path(directory) / "empty.sqlite3"
            with sqlite3.connect(database) as connection:
                connection.execute("CREATE TABLE snapshots(id INTEGER PRIMARY KEY)")
            with self.assertRaisesRegex(RuntimeError, "No imported"):
                record_evaluation(database)

    def test_cli_prints_success_and_parser_reports_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "portfolio.sqlite3"
            with sqlite3.connect(database) as connection:
                connection.execute("CREATE TABLE snapshots(id INTEGER PRIMARY KEY)")
                connection.execute("INSERT INTO snapshots VALUES (1)")
            with patch("builtins.print") as output:
                self.assertEqual(main(["--database", str(database)]), 0)
            self.assertIn("completion recorded", output.call_args.args[0])
            with self.assertRaises(SystemExit) as error:
                main(["--database", str(Path(directory) / "missing.sqlite3")])
            self.assertEqual(error.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
