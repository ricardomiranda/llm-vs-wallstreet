"""Tests for the rolling-peak market review trigger."""

from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta, timezone
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from security_research import (
    _date_from_timestamp,
    _fetch_news,
    _headline_is_relevant,
    _load_chart_context,
    _number,
    _parse_published_date,
    _get_json,
    calculate_rolling_peak_review,
    fetch_market_context,
)


class RollingPeakReviewTests(unittest.TestCase):
    """Verify coverage and drawdown boundaries for rolling peak reviews."""

    def test_covered_window_reports_peak_date_and_non_trigger(self) -> None:
        observations = [
            ("2025-11-08", 90.0),
            ("2025-11-10", 100.0),
            ("2026-11-06", 81.0),
        ]

        result = calculate_rolling_peak_review(
            observations, date.fromisoformat("2026-11-07")
        )

        self.assertEqual(result.peak_price, 100.0)
        self.assertEqual(result.peak_date, "2025-11-10")
        self.assertAlmostEqual(result.drawdown_percent or 0.0, -19.0)
        self.assertEqual(result.coverage_start, "2025-11-08")
        self.assertEqual(result.coverage_end, "2026-11-06")
        self.assertFalse(result.review_triggered)

    def test_exactly_twenty_percent_decline_triggers_review(self) -> None:
        observations = [
            ("2025-11-07", 100.0),
            ("2026-11-06", 80.0),
        ]

        result = calculate_rolling_peak_review(
            observations, date.fromisoformat("2026-11-07")
        )

        self.assertTrue(result.review_triggered)
        self.assertAlmostEqual(result.drawdown_percent or 0.0, -20.0)

    def test_insufficient_coverage_does_not_claim_trigger_status(self) -> None:
        observations = [
            ("2026-03-01", 100.0),
            ("2026-11-06", 50.0),
        ]

        result = calculate_rolling_peak_review(
            observations, date.fromisoformat("2026-11-07")
        )

        self.assertEqual(result.drawdown_percent, -50.0)
        self.assertIsNone(result.review_triggered)

    def test_current_day_observation_is_not_used_as_completed_close(self) -> None:
        observations = [
            ("2025-11-07", 100.0),
            ("2026-11-06", 90.0),
            ("2026-11-07", 20.0),
        ]

        result = calculate_rolling_peak_review(
            observations, date.fromisoformat("2026-11-07")
        )

        self.assertEqual(result.coverage_end, "2026-11-06")
        self.assertAlmostEqual(result.drawdown_percent or 0.0, -10.0)

    def test_empty_observations_return_unavailable(self) -> None:
        result = calculate_rolling_peak_review(
            [], date.fromisoformat("2026-11-07")
        )

        self.assertIsNone(result.peak_price)
        self.assertIsNone(result.review_triggered)

    def test_invalid_and_nonpositive_observations_are_ignored(self) -> None:
        result = calculate_rolling_peak_review(
            [("bad-date", 100), ("2026-11-06", 0)], date.fromisoformat("2026-11-07")
        )
        self.assertIsNone(result.peak_price)


class ResearchParsingTests(unittest.TestCase):
    """Test safe parsing and issuer-specific headline filtering."""

    def test_number_date_and_headline_helpers(self) -> None:
        self.assertEqual(_number(12), 12.0)
        self.assertIsNone(_number(True))
        self.assertIsNone(_number("12"))
        stamp = datetime(2026, 11, 7, tzinfo=timezone.utc).timestamp()
        self.assertEqual(_date_from_timestamp(stamp), "2026-11-07")
        self.assertIsNone(_date_from_timestamp("bad"))
        self.assertEqual(_parse_published_date("Sat, 07 Nov 2026 10:00:00 GMT"), "2026-11-07")
        self.assertIsNone(_parse_published_date("not a date"))
        self.assertTrue(_headline_is_relevant("Acme reports earnings", "ACME", "Acme Corp", None))
        self.assertFalse(_headline_is_relevant("Unrelated company news", "ACME", "Acme Corp", None))

    def test_get_json_wraps_network_and_rejects_non_object(self) -> None:
        from urllib.error import URLError

        with patch("security_research.urllib.request.urlopen", side_effect=URLError("offline")):
            with self.assertRaisesRegex(RuntimeError, "offline"):
                _get_json("https://example.test")
        response = unittest.mock.MagicMock()
        with patch("security_research.urllib.request.urlopen", return_value=response), \
             patch("security_research.json.load", return_value=[]):
            with self.assertRaisesRegex(RuntimeError, "Unexpected response"):
                _get_json("https://example.test")

    def test_chart_context_calculates_prices_and_metadata_fallback(self) -> None:
        today = date.today()
        start = today - timedelta(days=364)
        timestamps = [
            datetime.combine(start, datetime.min.time(), timezone.utc).timestamp(),
            datetime.combine(today - timedelta(days=1), datetime.min.time(), timezone.utc).timestamp(),
        ]
        payload = {"chart": {"result": [{
            "timestamp": timestamps,
            "indicators": {"quote": [{"close": [100, 80]}]},
            "meta": {
                "longName": "Acme Corporation", "fullExchangeName": "NYSE",
                "currency": "USD", "marketCap": 1234,
                "dividendYield": 0.02, "trailingAnnualDividendRate": 1.5,
            },
        }]}}
        with patch("security_research._get_json", return_value=payload):
            data, error = _load_chart_context("ACME")
        self.assertIsNone(error)
        self.assertEqual(data["issuer_name"], "Acme Corporation")
        self.assertEqual(data["latest_close"], 80.0)
        self.assertAlmostEqual(data["one_year_return_percent"], -20.0)  # type: ignore[misc]
        self.assertEqual(data["dividend_yield_percent"], 2.0)
        self.assertEqual(data["market_cap"], 1234.0)

        empty_payload = {"chart": {"result": [{"meta": {
            "regularMarketPrice": 10, "fiftyTwoWeekHigh": 12,
            "fiftyTwoWeekLow": 4, "exchangeName": "X", "currency": "EUR",
        }}]}}
        with patch("security_research._get_json", return_value=empty_payload):
            fallback, error = _load_chart_context("ACME")
        self.assertIsNone(error)
        self.assertEqual(fallback["latest_close"], 10.0)
        self.assertEqual(fallback["year_high"], 12.0)

    def test_chart_context_rejects_missing_result(self) -> None:
        with patch("security_research._get_json", return_value={"chart": {"result": []}}):
            with self.assertRaisesRegex(RuntimeError, "No chart data"):
                _load_chart_context("ACME")

    def test_news_filters_old_irrelevant_and_unsafe_links_and_categorizes(self) -> None:
        current_timestamp = datetime.now(timezone.utc).timestamp()
        yesterday = current_timestamp - 86400
        old = current_timestamp - 200 * 86400
        rows = [
            {"title": "Acme announces acquisition", "link": "https://news.test/a", "providerPublishTime": yesterday, "publisher": "Wire"},
            {"title": "Acme lawsuit investigation", "canonicalUrl": {"url": "https://news.test/b"}, "providerPublishTime": yesterday},
            {"title": "Acme unrelated", "link": "http://unsafe.test"},
            {"title": "Acme earnings", "link": "https://news.test/old", "providerPublishTime": old},
            {"title": "Other issuer earnings", "link": "https://news.test/no"},
        ]
        with patch("security_research._get_json", return_value={"news": rows}):
            news, error = _fetch_news("ACME", "Acme Inc", "ACME", "Acme Inc")
        self.assertIsNone(error)
        self.assertEqual(len(news), 2)
        self.assertEqual(news[0].event_type, "Merger / acquisition")
        self.assertEqual(news[1].event_type, "Regulatory / legal")

    def test_news_preserves_results_and_returns_error_after_network_failure(self) -> None:
        rows = [{"title": "Acme declares dividend", "link": "https://news.test/div"}]
        with patch("security_research._get_json", side_effect=[{"news": rows}, RuntimeError("failed")]):
            news, error = _fetch_news("ACME", "Acme Inc", "ACME", None)
        self.assertEqual(len(news), 1)
        self.assertEqual(news[0].event_type, "Dividend")
        self.assertEqual(error, "failed")

    def test_market_context_handles_chart_news_and_benchmark_errors(self) -> None:
        with patch("security_research._load_chart_context", side_effect=RuntimeError("chart down")), \
             patch("security_research._fetch_news", return_value=((), "news down")):
            context = fetch_market_context("ACME", "Acme Inc", "ACME")
        self.assertEqual(context.chart_error, "chart down")
        self.assertEqual(context.news_error, "news down")
        self.assertIsNone(context.latest_close)
        with patch("security_research._load_chart_context", side_effect=[({"one_year_return_percent": 4}, None), RuntimeError("no SPY")]), \
             patch("security_research._fetch_news", return_value=((), None)):
            context = fetch_market_context("ACME", "Acme Inc", "ACME")
        self.assertIsNone(context.benchmark_one_year_return_percent)
        self.assertEqual(context.one_year_return_percent, 4.0)

    def test_market_context_skips_benchmark_for_spy(self) -> None:
        with patch("security_research._load_chart_context", return_value=({"latest_close": 10}, None)) as chart, \
             patch("security_research._fetch_news", return_value=((), None)):
            context = fetch_market_context("SPY", "SPDR ETF", "SPY")
        chart.assert_called_once_with("SPY")
        self.assertEqual(context.provider_symbol, "SPY")


if __name__ == "__main__":
    unittest.main()
