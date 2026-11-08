"""Tests for dashboard data preparation and portfolio review helpers."""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from streamlit.testing.v1 import AppTest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from dashboard import (
    Row,
    auto_selected_security_report,
    buy_plan_path,
    buy_review_reminder_due,
    evaluation_reminder_due,
    filter_loss_reviews_by_position_value,
    format_eur,
    format_number,
    load_buy_plan,
    load_concentration_recommendation,
    load_dashboard_data,
    load_last_evaluation,
    load_loss_reviews_from_database,
    load_suggested_risk_candidates,
    risk_budget_selection,
    risk_widget_key,
    security_report_options,
    urgency_background_style,
)
from security_research import MarketContext, NewsItem
from security_research_notes import ResearchSource, SecurityResearchNote, save_security_research_note
from import_portfolio import CashBalance, SCHEMA, Position, Snapshot, import_snapshot
from update_prices import PRICE_SCHEMA, PriceRecord, DailyPrice, Security, store_price


class DashboardHelperTests(unittest.TestCase):
    """Cover formatting, selection, filtering, and reminder decisions."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.database = self.root / "portfolio.sqlite3"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def holding(
        security_id: str, symbol: str, description: str,
        value: str | int | float | None = 100,
    ) -> Row:
        return {"security_id": security_id, "symbol": symbol, "description": description,
                "position_value_eur": value}

    def create_database(self, *, priced: bool = False) -> None:
        with sqlite3.connect(self.database) as connection:
            connection.executescript(SCHEMA)
            import_snapshot(connection, Snapshot(
                "Test Broker", "2026-11-07", "statement.csv", "EUR", 200,
                positions=[
                    Position("A", "AAA", "Alpha Corp", "stock", "EUR", 3, 10, 30, 30, 100, -90),
                    Position("B", "BBB", "Beta Inc", "stock", "EUR", 1, 10, 10, 10, 10, -1),
                ],
                cash_balances=[CashBalance("EUR", 100, 100)],
            ))
            connection.execute("INSERT INTO position_limits VALUES ('A',NULL,NULL,5,'cap')")
            connection.executescript(PRICE_SCHEMA)
            if priced:
                for security_id, symbol, description, price in (
                    ("A", "AAA", "Alpha Corp", 10), ("B", "BBB", "Beta Inc", 10)
                ):
                    store_price(connection, PriceRecord(
                        Security(security_id, symbol, description, ("EUR",)), symbol,
                        DailyPrice("2026-11-06", price, "EUR"), "2026-11-06", 1.0,
                    ))

    def test_pure_helpers_cover_styles_search_autoselection_and_risk(self) -> None:
        self.assertIn("background-color", urgency_background_style(2))
        self.assertEqual(urgency_background_style("2"), "")
        holdings = [self.holding("A", "AAA", "Alpha Corp"), self.holding("B", "BBB", "Beta Inc")]
        options = security_report_options(holdings, " alpha ")
        self.assertEqual(len(options), 1)
        self.assertIs(auto_selected_security_report(options, "AAA"), holdings[0])
        self.assertIsNone(auto_selected_security_report(options, ""))
        self.assertIs(auto_selected_security_report(options, "alpha"), holdings[0])
        self.assertEqual(format_eur(1234.5), "€1,234.50")
        self.assertEqual(format_eur(None), "—")
        self.assertEqual(format_number(12.345), "12.35")
        self.assertEqual(format_number(None), "unavailable")
        reviews = [type("Review", (), {"security_id": "A"})(), type("Review", (), {"security_id": "B"})()]
        self.assertEqual(filter_loss_reviews_by_position_value(reviews, {"A": 100, "B": 10}, 50), reviews[:1])
        self.assertEqual(risk_budget_selection(self.database, holdings, {"A"}, {"A": False, "B": True}), {"B"})
        self.assertEqual(risk_budget_selection(self.database, holdings, set(), {}), set())
        self.assertTrue(risk_widget_key(self.database, "A").startswith("risk-choice-v2-"))
        self.assertTrue(evaluation_reminder_due(None))
        now = datetime.now(timezone.utc)
        self.assertFalse(evaluation_reminder_due(now - timedelta(hours=1), now))
        self.assertTrue(evaluation_reminder_due(now - timedelta(hours=25), now))
        self.assertTrue(buy_review_reminder_due(datetime(2026, 11, 1, tzinfo=timezone.utc)))
        self.assertFalse(buy_review_reminder_due(datetime(2026, 11, 2, tzinfo=timezone.utc)))

    def test_buy_plan_path_and_validation(self) -> None:
        self.assertEqual(buy_plan_path(self.database), self.root / "portfolio_buy_plan.json")
        self.assertIsNone(load_buy_plan(self.database))
        path = self.root / "portfolio_buy_plan.json"
        path.write_text("[]", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "JSON object"):
            load_buy_plan(self.database)
        path.write_text(json.dumps({"schema_version": 9}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "unsupported"):
            load_buy_plan(self.database)
        path.write_text(json.dumps({"schema_version": 1, "summary": "ok", "roles": ["bad"]}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "roles"):
            load_buy_plan(self.database)
        path.write_text(json.dumps({"schema_version": 1, "summary": "ok", "roles": [], "candidates": [], "assumptions": []}), encoding="utf-8")
        self.assertEqual(load_buy_plan(self.database)["summary"], "ok")  # type: ignore[index]

    def test_load_last_evaluation_handles_missing_valid_and_invalid_status(self) -> None:
        self.create_database()
        self.assertIsNone(load_last_evaluation(self.database))
        with sqlite3.connect(self.database) as connection:
            connection.execute("CREATE TABLE portfolio_evaluation_status(singleton_id INTEGER PRIMARY KEY, completed_at TEXT)")
            connection.execute("INSERT INTO portfolio_evaluation_status VALUES (1, 'not a date')")
        self.assertIsNone(load_last_evaluation(self.database))
        with sqlite3.connect(self.database) as connection:
            connection.execute("UPDATE portfolio_evaluation_status SET completed_at='2026-11-07T10:00:00'")
        self.assertEqual(load_last_evaluation(self.database).tzinfo, timezone.utc)  # type: ignore[union-attr]

    def test_load_dashboard_data_with_price_and_risk_views(self) -> None:
        self.create_database(priced=True)
        with sqlite3.connect(self.database) as connection:
            connection.execute("CREATE TABLE portfolio_risk_classifications(security_id TEXT, risk_accepted INTEGER)")
            connection.execute("INSERT INTO portfolio_risk_classifications VALUES ('A', 1)")
        summary, holdings, alerts, snapshots, risks = load_dashboard_data(self.database)
        self.assertEqual(summary["account_count"], 1)
        self.assertEqual(len(holdings), 2)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(risks, [{"security_id": "A", "risk_accepted": 1}])
        self.assertEqual(load_loss_reviews_from_database(self.database, 15)[0].security_id, "A")
        recommendations = load_suggested_risk_candidates(self.database)
        self.assertIn("A", recommendations)
        with sqlite3.connect(self.database) as connection:
            connection.execute("DROP VIEW partial_sell_recommendations")
            connection.execute(
                """CREATE VIEW partial_sell_recommendations AS SELECT
                   'A' AS security_id, 'AAA' AS symbol, 'Alpha Corp' AS description,
                   '2026-11-06' AS price_date, 10.0 AS price_eur,
                   20.0 AS current_weight_pct, 5.0 AS target_weight_pct,
                   1.5 AS recommended_sell_quantity, 15.0 AS recommended_sell_value_eur"""
            )
        self.assertEqual(load_concentration_recommendation(self.database, "A")["symbol"], "AAA")  # type: ignore[index]
        self.assertIsNone(load_concentration_recommendation(self.database, "missing"))

    def test_dashboard_data_without_price_views_and_empty_database_errors(self) -> None:
        self.create_database()
        _, holdings, _, snapshots, _ = load_dashboard_data(self.database)
        self.assertEqual(len(holdings), 2)
        self.assertIsNone(holdings[0]["price_date"])
        self.assertEqual(len(snapshots), 1)
        with sqlite3.connect(self.database) as connection:
            connection.execute("DROP TABLE snapshots")
        with self.assertRaisesRegex(RuntimeError, "no imported"):
            load_dashboard_data(self.database)

    def test_concentration_recommendation_without_view_is_none(self) -> None:
        self.create_database()
        self.assertIsNone(load_concentration_recommendation(self.database, "A"))

    def test_streamlit_app_renders_dashboard_for_local_database(self) -> None:
        self.create_database(priced=True)
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "scripts" / "dashboard.py"))
        app.run()
        app.sidebar.text_input[0].set_value(str(self.database))
        app.run()
        self.assertFalse(app.exception)
        self.assertIn("Portfolio Desk", [title.value for title in app.title])

    def test_streamlit_app_renders_selected_security_report_without_network(self) -> None:
        self.create_database(priced=True)
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "scripts" / "dashboard.py"))
        app.run()
        app.sidebar.text_input[0].set_value(str(self.database))
        app.run()
        app.text_input(key="individual_security_report_search").set_value("AAA")
        app.run()
        self.assertFalse(app.exception)
        rendered_text = " ".join(element.value for element in app.markdown if isinstance(element.value, str))
        self.assertIn("Alpha Corp", rendered_text)
        self.assertIn("Plain-English assessment", rendered_text)
        self.assertIn("No saved article research", rendered_text)

    def test_selected_report_renders_saved_research_and_market_context(self) -> None:
        from unittest.mock import patch

        from streamlit.testing.v1 import AppTest

        self.create_database(priced=True)
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                "INSERT INTO security_price_symbols VALUES ('A','Yahoo Finance','AAA','now')"
            )
        save_security_research_note(self.database, SecurityResearchNote(
            security_id="A", symbol="AAA", description="Alpha Corp",
            summary="Saved evidence summary", findings=["Revenue grew"],
            limitations=["Guidance remains uncertain"],
            sources=[ResearchSource("Annual report", "Issuer", "https://example.test/report", "2026-11-01", True)],
            urgency_score=5, position_value_eur=30.0,
            recommendation_impact="Reading did not change the assessment.",
        ))
        context = MarketContext(
            provider_symbol="AAA", issuer_name="Alpha Corp", exchange="NYSE",
            currency="USD", latest_close=10.5, price_date="2026-11-06",
            year_high=12.0, year_low=8.0, one_year_return_percent=5.0,
            drawdown_from_year_high_percent=-12.5, rolling_peak_price=12.0,
            rolling_peak_date="2026-06-01", rolling_peak_drawdown_percent=-12.5,
            rolling_peak_coverage_start="2025-11-01", rolling_peak_coverage_end="2026-11-06",
            rolling_peak_review_triggered=False, benchmark_symbol="SPY",
            benchmark_one_year_return_percent=4.0, market_cap=1000000.0,
            dividend_yield_percent=2.0, trailing_annual_dividend_rate=0.5,
            news=(NewsItem("Acme earnings", "Newswire", "https://news.test/item", "2026-11-05", "Earnings / outlook"),),
            chart_error=None, news_error=None,
        )
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "scripts" / "dashboard.py"))
        with patch("dashboard.cached_market_context", return_value=context):
            app.run()
            app.sidebar.text_input[0].set_value(str(self.database))
            app.run()
            app.text_input(key="individual_security_report_search").set_value("AAA")
            app.run()
        self.assertFalse(app.exception)
        rendered_text = " ".join(element.value for element in app.markdown if isinstance(element.value, str))
        self.assertIn("Saved evidence summary", rendered_text)
        self.assertIn("Latest close", [metric.label for metric in app.metric])


if __name__ == "__main__":
    unittest.main()
