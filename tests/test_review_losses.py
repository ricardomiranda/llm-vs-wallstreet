"""Tests for the broker cost-basis loss review threshold."""

from __future__ import annotations

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from review_losses import (
    DEFAULT_LOSS_THRESHOLD_PERCENT,
    calculate_review_urgency,
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


if __name__ == "__main__":
    unittest.main()
