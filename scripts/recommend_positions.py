"""Report partial-sell recommendations for positions above configured limits."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from typing import Sequence

from import_portfolio import DEFAULT_DATABASE
from update_prices import PRICE_SCHEMA


def report_recommendations(database: Path) -> int:
    """Print configured concentration limits and any eligible sell signals."""
    if not database.exists():
        raise FileNotFoundError(
            f"Portfolio database not found at {database}; import positions first"
        )
    with sqlite3.connect(database) as connection:
        connection.executescript(PRICE_SCHEMA)
        setting = connection.execute(
            """SELECT max_single_security_weight_pct
               FROM portfolio_settings WHERE singleton_id = 1"""
        ).fetchone()
        if setting is None:
            raise RuntimeError("The portfolio concentration setting is missing")
        limit_pct = float(setting[0])
        summary = connection.execute(
            "SELECT priced_security_count, unpriced_security_count, "
            "priced_portfolio_value_eur, latest_price_date, "
            "unconverted_cash_count, total_security_count "
            "FROM current_portfolio_value_eur"
        ).fetchone()
        if summary is None or summary[3] is None:
            print("No market prices are available; run scripts/update_prices.py first.")
            return 0
        (
            priced_count,
            unpriced_count,
            portfolio_value,
            latest_price_date,
            unconverted_cash_count,
            total_security_count,
        ) = summary
        unmapped_pct = (
            100.0 * int(unpriced_count) / int(total_security_count)
            if total_security_count else 100.0
        )
        if unmapped_pct >= 2.0 or unconverted_cash_count:
            print(
                f"No sell recommendations generated: {unpriced_count} of "
                f"{total_security_count} securities ({unmapped_pct:.2f}%) lack "
                f"matched prices; {unconverted_cash_count} cash balance(s) "
                "lack EUR conversion. Recommendations require fewer than 2% "
                "unpriced securities and converted cash."
            )
            return 0
        print(
            f"Portfolio value (unpriced holdings = €0): €{portfolio_value:,.2f}; "
            f"latest price date: "
            f"{latest_price_date}; {unpriced_count} of {total_security_count} "
            f"securities ({unmapped_pct:.2f}%) valued at €0; default max "
            f"single-security weight: {limit_pct:.2f}%"
        )
        recommendations = connection.execute(
            """SELECT symbol, description, current_quantity, price_eur,
                      current_weight_pct, target_weight_pct,
                      recommended_sell_quantity, recommended_sell_value_eur
               FROM partial_sell_recommendations
               ORDER BY current_weight_pct DESC"""
        ).fetchall()
        if not recommendations:
            print("No positions exceed their configured maximum portfolio weight.")
            return 0
        for row in recommendations:
            print(
                f"SELL PART: {row[0]} ({row[1]}) weighs {row[4]:.2f}% "
                f"(limit {row[5]:.2f}%). Consider selling about "
                f"{row[6]:.6g} units (≈ €{row[7]:,.2f}) at €{row[3]:,.2f} per unit."
            )
        return len(recommendations)


def main(arguments: Sequence[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    options = parser.parse_args(arguments)
    report_recommendations(options.database)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
