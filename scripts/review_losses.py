"""Flag reported unrealized losses for review without suggesting a sale."""

from __future__ import annotations

import argparse
import sqlite3
from datetime import date
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from import_portfolio import DEFAULT_DATABASE


DEFAULT_LOSS_THRESHOLD_PERCENT = 20.0


@dataclass(frozen=True)
class LossReview:
    """One reported holding that crossed the loss-review threshold."""

    broker: str
    statement_date: str
    security_id: str
    symbol: str
    description: str
    currency: str
    quantity: float
    cost_basis: float
    unrealized_pl: float
    first_seen_date: str
    days_since_first_seen: int
    loss_percent: float
    urgency_score: int


def calculate_review_urgency(
    loss_percent: float, threshold_percent: float = DEFAULT_LOSS_THRESHOLD_PERCENT
) -> int:
    """Map reported loss severity to a 0-5 review prompt score.

    Zero means the configured loss trigger was not reached. Once triggered,
    add one point per additional 10 percentage points of loss, capped at five.
    """
    if loss_percent > -threshold_percent:
        return 0
    additional_loss = abs(loss_percent) - threshold_percent
    return min(5, 1 + int(additional_loss // 10.0))


def load_loss_reviews(
    connection: sqlite3.Connection, threshold_percent: float
) -> tuple[list[LossReview], dict[str, int]]:
    """Load latest broker-reported loss flags and missing-data counts."""
    positions = connection.execute(
        """WITH ranked_snapshots AS (
                   SELECT id, account_id, as_of_date,
                          ROW_NUMBER() OVER (
                              PARTITION BY account_id
                              ORDER BY as_of_date DESC, id DESC
                          ) AS snapshot_rank
                   FROM snapshots
               ), first_seen AS (
                   SELECT s.account_id, p.security_id, p.currency,
                          MIN(s.as_of_date) AS first_seen_date
                   FROM positions AS p
                   JOIN snapshots AS s ON s.id = p.snapshot_id
                   GROUP BY s.account_id, p.security_id, p.currency
               )
               SELECT a.broker, s.as_of_date, p.security_id, p.symbol,
                      p.description, p.currency, p.quantity, p.cost_basis,
                      p.unrealized_pl, f.first_seen_date
               FROM positions AS p
               JOIN ranked_snapshots AS r
                 ON r.id = p.snapshot_id AND r.snapshot_rank = 1
               JOIN snapshots AS s ON s.id = p.snapshot_id
               JOIN accounts AS a ON a.id = s.account_id
               JOIN first_seen AS f
                 ON f.account_id = s.account_id
                AND f.security_id = p.security_id
                AND f.currency = p.currency
               ORDER BY a.broker, p.symbol, p.currency"""
    ).fetchall()
    reviews: list[LossReview] = []
    unavailable_by_broker: dict[str, int] = {}
    for row in positions:
        (
            broker,
            snapshot_date,
            security_id,
            symbol,
            description,
            currency,
            quantity,
            cost_basis,
            unrealized_pl,
            first_seen_date,
        ) = row
        if cost_basis is None or unrealized_pl is None or cost_basis <= 0:
            unavailable_by_broker[broker] = unavailable_by_broker.get(broker, 0) + 1
            continue
        loss_percent = 100.0 * float(unrealized_pl) / float(cost_basis)
        if loss_percent >= 0:
            continue
        first_seen = date.fromisoformat(first_seen_date)
        statement_day = date.fromisoformat(snapshot_date)
        reviews.append(
            LossReview(
                broker=broker,
                statement_date=snapshot_date,
                security_id=security_id,
                symbol=symbol,
                description=description,
                currency=currency,
                quantity=float(quantity),
                cost_basis=float(cost_basis),
                unrealized_pl=float(unrealized_pl),
                first_seen_date=first_seen_date,
                days_since_first_seen=(statement_day - first_seen).days,
                loss_percent=loss_percent,
                urgency_score=calculate_review_urgency(
                    loss_percent, threshold_percent
                ),
            )
        )
    return reviews, unavailable_by_broker


def report_loss_reviews(database: Path, threshold_percent: float) -> int:
    """Report current broker positions whose reported loss exceeds a threshold."""
    if not database.exists():
        raise FileNotFoundError(
            f"Portfolio database not found at {database}; import positions first"
        )
    with sqlite3.connect(database) as connection:
        reviews, unavailable_by_broker = load_loss_reviews(
            connection, threshold_percent
        )

    if not reviews and not unavailable_by_broker:
        print("No imported portfolio positions found.")
        return 0

    unavailable = sum(unavailable_by_broker.values())
    print(
        f"Loss review threshold: {threshold_percent:.1f}% of broker-reported cost basis. "
        "Urgency 0-5 measures loss severity only; it is not a sell recommendation."
    )
    for review in reviews:
        status = "REVIEW" if review.urgency_score else "MONITOR"
        print(
            f"{status} {review.urgency_score}/5: {review.symbol} "
            f"({review.description}), {review.broker} — "
            f"{review.loss_percent:.2f}% unrealized loss in {review.currency} "
            f"(P/L {review.unrealized_pl:,.2f}; cost basis {review.cost_basis:,.2f}); "
            f"statement {review.statement_date}. First seen in imported snapshots: "
            f"{review.first_seen_date} ({review.days_since_first_seen} days before "
            "this statement; not necessarily the purchase date)."
        )

    if not reviews:
        print("No current positions have a broker-reported unrealized loss.")
    if unavailable:
        broker_counts = ", ".join(
            f"{broker}: {count}"
            for broker, count in sorted(unavailable_by_broker.items())
        )
        print(
            f"Not assessed for missing/invalid cost basis or P/L: {unavailable} "
            f"position(s) ({broker_counts})."
        )
    print(
        f"Loss positions: {len(reviews)}; "
        f"above review threshold: "
        f"{sum(review.urgency_score > 0 for review in reviews)}; "
        f"not assessed for missing basis/P&L: {unavailable}. "
        "Statement P/L may exclude dividends; review total return, the investment "
        "thesis, and any material business changes before deciding what to do."
    )
    return len(reviews)


def main(arguments: Sequence[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument(
        "--threshold-percent",
        type=float,
        default=DEFAULT_LOSS_THRESHOLD_PERCENT,
        help=f"Loss percentage that triggers review (default: {DEFAULT_LOSS_THRESHOLD_PERCENT:g})",
    )
    options = parser.parse_args(arguments)
    if options.threshold_percent <= 0 or options.threshold_percent > 100:
        parser.error("--threshold-percent must be greater than 0 and at most 100")
    report_loss_reviews(options.database, options.threshold_percent)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
