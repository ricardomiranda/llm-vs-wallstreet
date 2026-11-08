"""Tests for concentration recommendation reporting and CLI behavior."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from import_portfolio import CashBalance, SCHEMA, Position, Snapshot, import_snapshot
from recommend_positions import main, report_recommendations
from update_prices import PRICE_SCHEMA, PriceRecord, DailyPrice, Security, store_price


class RecommendationReportTests(unittest.TestCase):
    """Test missing data, complete valuation, and recommendation output."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name) / "portfolio.sqlite3"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def create_database(self, *, priced: bool) -> None:
        if self.database.exists():
            self.database.unlink()
        with sqlite3.connect(self.database) as connection:
            connection.executescript(SCHEMA)
            import_snapshot(connection, Snapshot(
                "Test", "2026-11-07", "statement.csv", "EUR", 100,
                positions=[
                    Position("A", "AAA", "Alpha", "stock", "EUR", 9, 10, 90, 90),
                    Position("B", "BBB", "Beta", "stock", "EUR", 1, 10, 10, 10),
                ],
                cash_balances=[CashBalance("EUR", 10, 10)],
            ))
            connection.execute("INSERT INTO position_limits VALUES ('A',NULL,NULL,50,'limit')")
            connection.executescript(PRICE_SCHEMA)
            if priced:
                for security_id, symbol, name, close in (("A", "AAA", "Alpha", 10), ("B", "BBB", "Beta", 10)):
                    store_price(connection, PriceRecord(
                        Security(security_id, symbol, name, ("EUR",)), symbol,
                        DailyPrice("2026-11-06", close, "EUR"), "2026-11-06", 1,
                    ))
                    connection.execute(
                        "INSERT INTO security_price_symbols VALUES (?, 'Yahoo Finance', ?, 'now')",
                        (security_id, symbol),
                    )

    def test_missing_database_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            report_recommendations(self.database)

    def test_unavailable_price_and_unpriced_holdings_suppress_recommendations(self) -> None:
        self.create_database(priced=False)
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(report_recommendations(self.database), 0)
        self.assertIn("No market prices", output.getvalue())
        self.create_database(priced=True)
        with sqlite3.connect(self.database) as connection:
            connection.execute("DELETE FROM security_price_history WHERE security_id='B'")
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(report_recommendations(self.database), 0)
        self.assertIn("lack matched prices", output.getvalue())

    def test_complete_pricing_reports_sell_recommendation(self) -> None:
        self.create_database(priced=True)
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(report_recommendations(self.database), 1)
        self.assertIn("SELL PART: AAA", output.getvalue())

    def test_cli_returns_success_for_selected_database(self) -> None:
        self.create_database(priced=True)
        self.assertEqual(main(["--database", str(self.database)]), 0)


if __name__ == "__main__":
    unittest.main()
