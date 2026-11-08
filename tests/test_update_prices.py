"""Tests for deterministic price mapping, conversion, and storage logic."""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from contextlib import redirect_stdout
from io import StringIO

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from import_portfolio import SCHEMA, Position, Snapshot, import_snapshot
from update_prices import (
    PRICE_SCHEMA,
    DailyPrice,
    PriceRecord,
    Security,
    fetch_daily_price,
    fetch_eur_rate,
    fetch_price_record,
    http_json,
    load_provider_symbols,
    load_securities,
    main,
    meaningful_name_terms,
    resolve_provider_symbol,
    store_price,
    update_database,
)


class SymbolAndQuoteTests(unittest.TestCase):
    """Exercise reviewed mappings and conservative search evidence."""

    def test_meaningful_terms_remove_stop_words(self) -> None:
        self.assertEqual(meaningful_name_terms("The Acme Corp. Class A"), {"ACME"})

    def test_reviewed_symbol_does_not_make_network_request(self) -> None:
        security = Security("US00206R1023", "T", "AT&T Inc", ("USD",))
        with patch("update_prices.http_json") as request:
            self.assertEqual(resolve_provider_symbol(security), "T")
            request.assert_not_called()

    def test_search_uses_exact_ticker_only_with_name_overlap(self) -> None:
        security = Security("CUSIP", "ACME", "Acme Corp", ("USD",))
        with patch("update_prices.http_json", return_value={"quotes": [
            {"quoteType": "EQUITY", "symbol": "ACME", "longname": "Acme Inc"}
        ]}):
            self.assertEqual(resolve_provider_symbol(security), "ACME")

    def test_search_rejects_bad_or_ambiguous_evidence(self) -> None:
        security = Security("CUSIP", "CUSIP", "Acme Holdings", ("USD",))
        irrelevant = {"quoteType": "CRYPTOCURRENCY", "symbol": "ACME", "longname": "Acme Holdings"}
        ambiguous = [
            {"quoteType": "EQUITY", "symbol": "ACME", "longname": "Acme Holdings"},
            {"quoteType": "EQUITY", "symbol": "ACM2", "longname": "Acme Holdings"},
        ]
        with patch("update_prices.http_json", side_effect=[
            {"quotes": [irrelevant]}, {"quotes": ambiguous}
        ]):
            self.assertEqual(resolve_provider_symbol(security), "")

    def test_search_uses_qualified_name_match_and_retries_bad_quote_shapes(self) -> None:
        security = Security("CUSIP", "CUSIP", "Acme Holdings", ("USD",))
        with patch("update_prices.http_json", return_value={
            "quotes": [None, {"quoteType": "EQUITY", "symbol": "ACME", "longname": "Acme Holdings", "score": 100000}]
        }):
            self.assertEqual(resolve_provider_symbol(security), "ACME")
        exact = Security("CUSIP", "ACME", "Acme Holdings", ("USD",))
        with patch("update_prices.http_json", return_value={"quotes": [
            {"quoteType": "ETF", "symbol": "ACME", "shortname": "Acme Holdings", "isYahooFinance": False}
        ]}):
            self.assertEqual(resolve_provider_symbol(exact), "")

    def test_http_json_rejects_invalid_and_non_object_responses(self) -> None:
        with patch("update_prices.urllib.request.urlopen", side_effect=TimeoutError("late")):
            with self.assertRaisesRegex(RuntimeError, "Request failed"):
                http_json("https://example.test")
        response = unittest.mock.MagicMock()
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        with patch("update_prices.urllib.request.urlopen", return_value=response), \
             patch("update_prices.json.load", return_value=[]):
            with self.assertRaisesRegex(RuntimeError, "Unexpected JSON"):
                http_json("https://example.test")


class PriceFetchTests(unittest.TestCase):
    """Test completed-close selection, FX scaling, and request caching."""

    def test_fetch_daily_price_ignores_today_and_incomplete_rows(self) -> None:
        today = datetime.now(timezone.utc).date()
        yesterday = datetime.combine(today, datetime.min.time(), timezone.utc).timestamp() - 86400
        current = datetime.combine(today, datetime.min.time(), timezone.utc).timestamp()
        payload = {"chart": {"result": [{
            "timestamp": [yesterday, current],
            "indicators": {"quote": [{"close": [42.5, 99.0]}]},
            "meta": {"currency": "USD"},
        }]}}
        with patch("update_prices.http_json", return_value=payload):
            price = fetch_daily_price("TEST")
        self.assertEqual(price.price_date, datetime.fromtimestamp(yesterday, timezone.utc).date().isoformat())
        self.assertEqual(price.close, 42.5)
        self.assertEqual(price.currency, "USD")

    def test_fetch_daily_price_reports_missing_chart_rows(self) -> None:
        for payload, message in (({"chart": {"result": []}}, "No chart data"),
                                 ({"chart": {"result": [{"timestamp": [], "indicators": {}}]}}, "Incomplete chart"),
                                 ({"chart": {"result": [{"timestamp": [], "indicators": {"quote": [{"close": []}]}, "meta": {"currency": "USD"}}]}}, "No usable")):
            with patch("update_prices.http_json", return_value=payload), \
                 self.subTest(message=message), self.assertRaisesRegex(RuntimeError, message):
                fetch_daily_price("TEST")

    def test_fetch_eur_rate_handles_eur_gbp_minor_units_and_errors(self) -> None:
        with patch("update_prices.http_json") as request:
            self.assertEqual(fetch_eur_rate("EUR", "2026-11-07"), ("2026-11-07", 1.0))
            request.assert_not_called()
        with patch("update_prices.http_json", return_value={
            "date": "2026-11-06", "rates": {"EUR": 1.17}
        }) as request:
            fx_date, rate = fetch_eur_rate("GBp", "2026-11-07")
            self.assertEqual(fx_date, "2026-11-06")
            self.assertAlmostEqual(rate, 0.0117)
            self.assertIn("from=GBP", request.call_args.args[0])
        for payload in ({"date": "2026-11-06", "rates": {"EUR": 0}},
                        {"rates": {"EUR": 1.2}}):
            with patch("update_prices.http_json", return_value=payload), \
                 self.assertRaises(RuntimeError):
                fetch_eur_rate("USD", "2026-11-07")

    def test_fetch_price_record_reuses_fx_and_requires_symbol_mapping(self) -> None:
        security = Security("ID", "SYM", "Example", ("USD",))
        price = DailyPrice("2026-11-06", 10, "USD")
        rates = {("USD", "2026-11-06"): ("2026-11-06", 0.9)}
        with patch("update_prices.resolve_provider_symbol", return_value="SYM"), \
             patch("update_prices.fetch_daily_price", return_value=price), \
             patch("update_prices.fetch_eur_rate") as fx:
            record = fetch_price_record(security, {}, rates)
        fx.assert_not_called()
        self.assertEqual(record.price_eur, 9.0)
        with patch("update_prices.resolve_provider_symbol", return_value=""):
            with self.assertRaisesRegex(RuntimeError, "Could not confidently map"):
                fetch_price_record(security, {}, {})
        with patch("update_prices.resolve_provider_symbol", return_value="SYM"), \
             patch("update_prices.fetch_daily_price", return_value=price), \
             patch("update_prices.fetch_eur_rate", return_value=("2026-11-06", 0.8)) as fx:
            record = fetch_price_record(security, {}, {})
        fx.assert_called_once_with("USD", "2026-11-06")
        self.assertEqual(record.eur_per_original_unit, 0.8)


class PriceDatabaseTests(unittest.TestCase):
    """Verify holdings loading and idempotent stored price/FX values."""

    def test_load_securities_selects_latest_snapshot_per_account(self) -> None:
        with sqlite3.connect(":memory:") as connection:
            connection.executescript(SCHEMA)
            for date, source in (("2026-01-01", "old.csv"), ("2026-11-07", "new.csv")):
                import_snapshot(connection, Snapshot(
                    "Test", date, source, "EUR", 10,
                    positions=[Position("ID", "SYM", "Company", "stock", "EUR", 1, 10, 10, 10)],
                ))
            connection.executescript(PRICE_SCHEMA)
            self.assertEqual(load_securities(connection), [Security("ID", "SYM", "Company", ("EUR",))])
            connection.execute(
                "INSERT INTO security_price_symbols VALUES ('ID','Yahoo Finance','SYM','now')"
            )
            self.assertEqual(load_provider_symbols(connection), {"ID": "SYM"})

    def test_store_price_upserts_history_and_fx(self) -> None:
        with sqlite3.connect(":memory:") as connection:
            connection.executescript(SCHEMA)
            connection.executescript(PRICE_SCHEMA)
            security = Security("ID", "SYM", "Company", ("GBp",))
            record = PriceRecord(security, "SYM.L", DailyPrice("2026-11-06", 250, "GBp"), "2026-11-06", 0.012)
            store_price(connection, record)
            store_price(connection, record)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM security_price_history").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM fx_rate_history").fetchone()[0], 2)
            self.assertAlmostEqual(record.price_eur, 3.0)

    def test_update_database_keeps_successes_when_one_fetch_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "portfolio.sqlite3"
            with sqlite3.connect(database) as connection:
                connection.executescript(SCHEMA)
                import_snapshot(connection, Snapshot(
                    "Test", "2026-11-07", "input.csv", "EUR", 20,
                    positions=[
                        Position("A", "AAA", "Alpha", "stock", "EUR", 1, 10, 10, 10),
                        Position("B", "BBB", "Beta", "stock", "EUR", 1, 10, 10, 10),
                    ],
                ))
            records = {
                "A": PriceRecord(Security("A", "AAA", "Alpha", ("EUR",)), "AAA", DailyPrice("2026-11-06", 10, "EUR"), "2026-11-06", 1.0)
            }
            def fake_fetch(security: Security, _symbols: dict[str, str], _fx: dict[tuple[str, str], tuple[str, float]]) -> PriceRecord:
                if security.security_id == "B":
                    raise RuntimeError("network unavailable")
                return records[security.security_id]
            with patch("update_prices.fetch_price_record", side_effect=fake_fetch), \
                 patch("update_prices.time.sleep"):
                succeeded, failures = update_database(database, delay_seconds=0)
            self.assertEqual(succeeded, 1)
            self.assertEqual(len(failures), 1)
            with sqlite3.connect(database) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM security_price_history").fetchone()[0], 1)

    def test_update_database_filters_requested_symbol_and_replaces_stale_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "portfolio.sqlite3"
            with sqlite3.connect(database) as connection:
                connection.executescript(SCHEMA)
                import_snapshot(connection, Snapshot(
                    "Test", "2026-11-07", "input.csv", "EUR", 20,
                    positions=[
                        Position("A", "AAA", "Alpha", "stock", "EUR", 1, 10, 10, 10),
                        Position("B", "BBB", "Beta", "stock", "EUR", 1, 10, 10, 10),
                    ],
                ))
                connection.executescript(PRICE_SCHEMA)
                connection.execute("INSERT INTO security_price_symbols VALUES ('A','Yahoo Finance','OLD','yesterday')")
            record = PriceRecord(Security("A", "AAA", "Alpha", ("EUR",)), "NEW", DailyPrice("2026-11-06", 10, "EUR"), "2026-11-06", 1)
            with patch("update_prices.fetch_price_record", return_value=record), patch("update_prices.time.sleep"):
                self.assertEqual(update_database(database, requested_symbols={"AAA"}), (1, []))
            with sqlite3.connect(database) as connection:
                self.assertEqual(connection.execute("SELECT provider_symbol FROM security_price_symbols WHERE security_id='A'").fetchone()[0], "NEW")
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM security_price_history WHERE security_id='B'").fetchone()[0], 0)
            with self.assertRaisesRegex(ValueError, "No positions matched"):
                update_database(database, requested_symbols={"MISSING"})

    def test_update_database_migrates_legacy_price_table_and_cli_reports_failures(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "portfolio.sqlite3"
            with sqlite3.connect(database) as connection:
                connection.executescript(SCHEMA)
                import_snapshot(connection, Snapshot("Test", "2026-11-07", "input.csv", "EUR", 10,
                    positions=[Position("A", "AAA", "Alpha", "stock", "EUR", 1, 10, 10, 10)]))
                connection.executescript(PRICE_SCHEMA)
                connection.execute("DROP VIEW current_security_values_eur")
                connection.execute("DROP VIEW current_portfolio_value_eur")
                connection.execute("DROP TABLE security_price_history")
                connection.execute("""CREATE TABLE security_price_history (
                    id INTEGER PRIMARY KEY, security_id TEXT, symbol TEXT, description TEXT,
                    provider TEXT, provider_symbol TEXT, price_date TEXT, fetched_at TEXT,
                    original_price REAL, original_currency TEXT, eur_per_original_unit REAL,
                    price_eur REAL, UNIQUE(security_id, provider, price_date))""")
            with patch("update_prices.fetch_price_record", side_effect=RuntimeError("offline")), patch("update_prices.time.sleep"):
                succeeded, failures = update_database(database)
            self.assertEqual(succeeded, 0)
            self.assertEqual(len(failures), 1)
            self.assertTrue(update_database.__doc__)
        with patch("update_prices.update_database", return_value=(0, ["AAA failed"])):
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(["--database", "db.sqlite", "--symbol", "aaa"]), 1)
            self.assertIn("Could not update", output.getvalue())
        with patch("update_prices.update_database", return_value=(1, [])), redirect_stdout(StringIO()):
            self.assertEqual(main(["--database", "db.sqlite", "--delay", "0"]), 0)
        with self.assertRaises(SystemExit) as error:
            main(["--delay", "-1"])
        self.assertEqual(error.exception.code, 2)

    def test_update_database_requires_existing_database(self) -> None:
        with self.assertRaises(FileNotFoundError):
            update_database(Path("/missing/portfolio.sqlite3"))


if __name__ == "__main__":
    unittest.main()
