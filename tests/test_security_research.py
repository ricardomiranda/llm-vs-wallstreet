"""Tests for the rolling-peak market review trigger."""

from __future__ import annotations

import unittest
from datetime import date

from scripts.security_research import calculate_rolling_peak_review


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


if __name__ == "__main__":
    unittest.main()
