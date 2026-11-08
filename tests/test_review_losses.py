"""Tests for the broker cost-basis loss review threshold."""

from __future__ import annotations

import unittest
import sys
import sqlite3
import tempfile
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from review_losses import (
    DEFAULT_LOSS_THRESHOLD_PERCENT,
    calculate_review_urgency,
    load_loss_reviews,
    main,
    report_loss_reviews,
)


class CostBasisReviewTests(unittest.TestCase):
    """Verify the 15% default cost-basis review rule and score boundaries."""

    def test_default_cost_basis_review_threshold_is_fifteen_percent(self) -> None:
        self.assertEqual(DEFAULT_LOSS_THRESHOLD_PERCENT, 15.0)
        self.assertEqual(calculate_review_urgency(-14.99), 0)
        self.assertEqual(calculate_review_urgency(-15.0), 1)

    def test_custom_threshold_is_applied_to_review_score(self) -> None:
        self.assertEqual(calculate_review_urgency(-10.0, 10.0), 1)
        self.assertEqual(calculate_review_urgency(-9.99, 10.0), 0)

    def test_load_reviews_filters_current_losses_and_counts_missing_data(self) -> None:
        with sqlite3.connect(":memory:") as connection:
            connection.executescript("""
                CREATE TABLE accounts(id INTEGER PRIMARY KEY, broker TEXT);
                CREATE TABLE snapshots(id INTEGER PRIMARY KEY, account_id INTEGER, as_of_date TEXT);
                CREATE TABLE positions(snapshot_id INTEGER, security_id TEXT, symbol TEXT,
                    description TEXT, currency TEXT, quantity REAL, cost_basis REAL, unrealized_pl REAL);
                INSERT INTO accounts VALUES (1, 'Broker');
                INSERT INTO snapshots VALUES (1, 1, '2026-01-01');
                INSERT INTO snapshots VALUES (2, 1, '2026-11-07');
                INSERT INTO positions VALUES (1, 'A', 'AAA', 'Alpha', 'EUR', 2, 100, -20);
                INSERT INTO positions VALUES (2, 'A', 'AAA', 'Alpha', 'EUR', 2, 100, -20);
                INSERT INTO positions VALUES (2, 'B', 'BBB', 'Beta', 'EUR', 1, 0, -5);
                INSERT INTO positions VALUES (2, 'C', 'CCC', 'Gamma', 'EUR', 1, 100, 5);
            """)
            reviews, unavailable = load_loss_reviews(connection, 15)
        self.assertEqual(len(reviews), 1)
        self.assertEqual(reviews[0].days_since_first_seen, 310)
        self.assertEqual(reviews[0].urgency_score, 1)
        self.assertEqual(unavailable, {"Broker": 1})

    def test_report_and_cli_cover_empty_and_unavailable_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "portfolio.sqlite3"
            with sqlite3.connect(database) as connection:
                connection.executescript("""
                    CREATE TABLE accounts(id INTEGER PRIMARY KEY, broker TEXT);
                    CREATE TABLE snapshots(id INTEGER PRIMARY KEY, account_id INTEGER, as_of_date TEXT);
                    CREATE TABLE positions(snapshot_id INTEGER, security_id TEXT, symbol TEXT,
                        description TEXT, currency TEXT, quantity REAL, cost_basis REAL, unrealized_pl REAL);
                    INSERT INTO accounts VALUES (1, 'Broker');
                    INSERT INTO snapshots VALUES (1, 1, '2026-11-07');
                    INSERT INTO positions VALUES (1, 'A', 'AAA', 'Alpha', 'EUR', 2, 100, -40);
                    INSERT INTO positions VALUES (1, 'B', 'BBB', 'Beta', 'EUR', 1, 100, 0);
                """)
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(report_loss_reviews(database, 15), 1)
            self.assertIn("REVIEW 3/5", output.getvalue())
            self.assertIn("not assessed", output.getvalue())
            self.assertEqual(main(["--database", str(database), "--threshold-percent", "20"]), 0)
            with self.assertRaises(SystemExit) as error:
                main(["--threshold-percent", "0"])
            self.assertEqual(error.exception.code, 2)
            missing = Path(directory) / "missing.db"
            with self.assertRaises(FileNotFoundError):
                report_loss_reviews(missing, 15)

    def test_empty_database_reports_no_positions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "portfolio.sqlite3"
            with sqlite3.connect(database) as connection:
                connection.executescript("""
                    CREATE TABLE accounts(id INTEGER, broker TEXT);
                    CREATE TABLE snapshots(id INTEGER, account_id INTEGER, as_of_date TEXT);
                    CREATE TABLE positions(snapshot_id INTEGER, security_id TEXT, symbol TEXT,
                        description TEXT, currency TEXT, quantity REAL, cost_basis REAL, unrealized_pl REAL);
                """)
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(report_loss_reviews(database, 15), 0)
            self.assertIn("No imported portfolio positions", output.getvalue())


if __name__ == "__main__":
    unittest.main()
