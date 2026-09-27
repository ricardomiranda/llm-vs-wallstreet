"""Fetch delayed daily security prices and persist source and EUR values."""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence
from zoneinfo import ZoneInfo

from import_portfolio import DEFAULT_DATABASE
from reviewed_price_symbols import REVIEWED_YAHOO_SYMBOLS


YAHOO_SEARCH_URL = "https://query1.finance.yahoo.com/v1/finance/search"
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart"
FRANKFURTER_URL = "https://api.frankfurter.dev/v1"
USER_AGENT = "Mozilla/5.0 (compatible; portfolio-price-updater/1.0)"
COMPANY_STOP_WORDS = {
    "AG", "ADR", "A", "AND", "CLASS", "CL", "CO", "CORP", "CORPORATION",
    "INC", "LIMITED", "LTD", "PLC", "SA", "SE", "THE", "HOLDINGS",
}


PRICE_SCHEMA = """
CREATE TABLE IF NOT EXISTS security_price_symbols (
    security_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    provider_symbol TEXT NOT NULL,
    mapped_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS security_price_history (
    id INTEGER PRIMARY KEY,
    security_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    description TEXT NOT NULL,
    provider TEXT NOT NULL,
    provider_symbol TEXT NOT NULL,
    price_date TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    original_price REAL NOT NULL,
    original_currency TEXT NOT NULL,
    fx_date TEXT NOT NULL,
    eur_per_original_unit REAL NOT NULL,
    price_eur REAL NOT NULL,
    UNIQUE(security_id, provider, price_date)
);
CREATE INDEX IF NOT EXISTS idx_price_history_security_date
    ON security_price_history(security_id, price_date);
CREATE TABLE IF NOT EXISTS fx_rate_history (
    currency TEXT NOT NULL,
    rate_date TEXT NOT NULL,
    provider TEXT NOT NULL,
    eur_per_unit REAL NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY(currency, rate_date, provider)
);
CREATE TABLE IF NOT EXISTS portfolio_settings (
    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
    max_single_security_weight_pct REAL NOT NULL DEFAULT 10.0
        CHECK (max_single_security_weight_pct > 0
               AND max_single_security_weight_pct <= 100)
);
INSERT OR IGNORE INTO portfolio_settings(
    singleton_id, max_single_security_weight_pct
) VALUES (1, 10.0);
DROP VIEW IF EXISTS partial_sell_recommendations;
DROP VIEW IF EXISTS latest_security_prices;
CREATE VIEW latest_security_prices AS
SELECT p.*
FROM security_price_history AS p
JOIN security_price_symbols AS symbols
  ON symbols.security_id = p.security_id
 AND symbols.provider = p.provider
 AND symbols.provider_symbol = p.provider_symbol
JOIN (
    SELECT security_id, MAX(price_date) AS latest_date
    FROM security_price_history
    GROUP BY security_id
) AS latest
  ON latest.security_id = p.security_id
 AND latest.latest_date = p.price_date;
DROP VIEW IF EXISTS current_security_values_eur;
CREATE VIEW IF NOT EXISTS current_security_values_eur AS
WITH ranked_snapshots AS (
    SELECT id, account_id,
           ROW_NUMBER() OVER (
               PARTITION BY account_id ORDER BY as_of_date DESC, id DESC
           ) AS snapshot_rank
    FROM snapshots
), current_positions AS (
    SELECT p.security_id,
           COALESCE(MAX(CASE WHEN p.symbol != p.security_id THEN p.symbol END),
                    MAX(p.symbol)) AS symbol,
           MAX(p.description) AS description,
           SUM(p.quantity) AS quantity
    FROM positions AS p
    JOIN ranked_snapshots AS s ON s.id = p.snapshot_id
    WHERE s.snapshot_rank = 1
    GROUP BY p.security_id
)
SELECT
    p.security_id,
    MAX(p.symbol) AS symbol,
    MAX(p.description) AS description,
    SUM(p.quantity) AS quantity,
    q.price_date,
    q.original_price,
    q.original_currency,
    q.fx_date,
    q.eur_per_original_unit,
    q.price_eur,
    SUM(p.quantity) * q.price_eur AS position_value_eur
FROM current_positions AS p
JOIN latest_security_prices AS q ON q.security_id = p.security_id
GROUP BY p.security_id, q.price_date;
DROP VIEW IF EXISTS current_portfolio_value_eur;
CREATE VIEW IF NOT EXISTS current_portfolio_value_eur AS
WITH current_snapshots AS (
    SELECT id, account_id,
           ROW_NUMBER() OVER (
               PARTITION BY account_id ORDER BY as_of_date DESC, id DESC
           ) AS snapshot_rank
    FROM snapshots
), all_current_positions AS (
    SELECT p.security_id, SUM(p.quantity) AS quantity
    FROM positions AS p
    JOIN current_snapshots AS s ON s.id = p.snapshot_id
    WHERE s.snapshot_rank = 1
    GROUP BY p.security_id
), position_total AS (
    SELECT
        SUM(CASE WHEN q.security_id IS NOT NULL
                 THEN p.quantity * q.price_eur ELSE 0.0 END) AS priced_value_eur,
        SUM(CASE WHEN q.security_id IS NULL THEN 1 ELSE 0 END) AS unpriced_count,
        SUM(CASE WHEN q.security_id IS NOT NULL THEN 1 ELSE 0 END) AS priced_count
    FROM all_current_positions AS p
    LEFT JOIN latest_security_prices AS q ON q.security_id = p.security_id
), current_cash AS (
    SELECT b.currency, b.amount,
           CASE
               WHEN b.currency = 'EUR' THEN 1.0
               ELSE (
                   SELECT fx.eur_per_unit
                   FROM fx_rate_history AS fx
                   WHERE fx.currency = b.currency
                   ORDER BY fx.rate_date DESC
                   LIMIT 1
               )
           END AS eur_per_unit
    FROM cash_balances AS b
    JOIN current_snapshots AS s ON s.id = b.snapshot_id
    WHERE s.snapshot_rank = 1
), cash_total AS (
    SELECT SUM(amount * eur_per_unit) AS cash_value_eur,
           SUM(CASE WHEN amount != 0 AND eur_per_unit IS NULL THEN 1 ELSE 0 END)
               AS unconverted_cash_count
    FROM current_cash
)
SELECT
    (SELECT priced_value_eur FROM position_total) AS priced_positions_eur,
    (SELECT cash_value_eur FROM cash_total) AS cash_value_eur,
    (SELECT priced_value_eur FROM position_total)
      + (SELECT cash_value_eur FROM cash_total)
        AS priced_portfolio_value_eur,
    (SELECT priced_count FROM position_total) AS priced_security_count,
    (SELECT unpriced_count FROM position_total) AS unpriced_security_count,
    (SELECT MAX(price_date) FROM latest_security_prices) AS latest_price_date,
    (SELECT unconverted_cash_count FROM cash_total) AS unconverted_cash_count,
    (SELECT COUNT(*) FROM all_current_positions) AS total_security_count;
DROP VIEW IF EXISTS partial_sell_recommendations;
CREATE VIEW partial_sell_recommendations AS
WITH portfolio AS (
    SELECT * FROM current_portfolio_value_eur
), thresholds AS (
    SELECT max_single_security_weight_pct
    FROM portfolio_settings
    WHERE singleton_id = 1
), exposures AS (
    SELECT
        p.*,
        portfolio.priced_portfolio_value_eur AS portfolio_value_eur,
        COALESCE(l.max_portfolio_pct, thresholds.max_single_security_weight_pct)
            AS max_weight_pct,
        100.0 * p.position_value_eur
            / NULLIF(portfolio.priced_portfolio_value_eur, 0) AS current_weight_pct
    FROM current_security_values_eur AS p
    CROSS JOIN portfolio
    CROSS JOIN thresholds
    LEFT JOIN position_limits AS l ON l.security_id = p.security_id
    WHERE portfolio.total_security_count > 0
      AND 100.0 * portfolio.unpriced_security_count
              / portfolio.total_security_count < 2.0
      AND portfolio.unconverted_cash_count = 0
      AND portfolio.priced_portfolio_value_eur > 0
)
SELECT
    security_id,
    symbol,
    description,
    quantity AS current_quantity,
    price_date,
    price_eur,
    position_value_eur,
    portfolio_value_eur,
    current_weight_pct,
    max_weight_pct AS target_weight_pct,
    position_value_eur
        - portfolio_value_eur * max_weight_pct / 100.0 AS recommended_sell_value_eur,
    (position_value_eur
        - portfolio_value_eur * max_weight_pct / 100.0) / price_eur
        AS recommended_sell_quantity
FROM exposures
WHERE current_weight_pct > max_weight_pct
  AND price_eur > 0;
"""


@dataclass(frozen=True)
class Security:
    """Distinct instrument identity held in the imported snapshots."""

    security_id: str
    symbol: str
    description: str
    currencies: tuple[str, ...]


@dataclass(frozen=True)
class DailyPrice:
    """Daily closing price and its source currency."""

    price_date: str
    close: float
    currency: str


@dataclass(frozen=True)
class PriceRecord:
    """Fetched price with FX conversion ready for database storage."""

    security: Security
    provider_symbol: str
    price: DailyPrice
    fx_date: str
    eur_per_original_unit: float

    @property
    def price_eur(self) -> float:
        """Close price converted into euros."""
        return self.price.close * self.eur_per_original_unit


def http_json(url: str) -> dict[str, Any]:
    """Fetch JSON from a public endpoint with a descriptive network error."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Request failed for {url}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"Unexpected JSON response from {url}")
    return payload


def load_securities(connection: sqlite3.Connection) -> list[Security]:
    """Load distinct positions from each account's latest snapshot."""
    rows = connection.execute(
        """WITH ranked_snapshots AS (
               SELECT id, account_id,
                      ROW_NUMBER() OVER (
                          PARTITION BY account_id ORDER BY as_of_date DESC, id DESC
                      ) AS snapshot_rank
               FROM snapshots
           )
           SELECT p.security_id,
                  COALESCE(MAX(CASE WHEN p.symbol != p.security_id
                                    THEN p.symbol END), MAX(p.symbol)),
                  MAX(p.description),
                  GROUP_CONCAT(DISTINCT p.currency)
           FROM positions AS p
           JOIN ranked_snapshots AS s ON s.id = p.snapshot_id
           WHERE s.snapshot_rank = 1
           GROUP BY p.security_id
           ORDER BY 2"""
    )
    return [
        Security(row[0], row[1], row[2], tuple((row[3] or "").split(",")))
        for row in rows
    ]


def resolve_provider_symbol(security: Security) -> str:
    """Resolve a broker ticker/ISIN to a Yahoo Finance symbol."""
    reviewed_symbol = REVIEWED_YAHOO_SYMBOLS.get(security.security_id)
    if reviewed_symbol is not None:
        return reviewed_symbol

    source_terms = meaningful_name_terms(security.description)
    queries = [security.symbol] if security.symbol != security.security_id else []
    queries.append(security.description)
    for search_query in queries:
        parameters = urllib.parse.urlencode(
            {"q": search_query, "quotesCount": 30, "newsCount": 0}
        )
        result = http_json(f"{YAHOO_SEARCH_URL}?{parameters}")
        quotes = result.get("quotes", [])
        if not isinstance(quotes, list):
            continue
        ranked: list[tuple[float, str]] = []
        for quote in quotes:
            if not isinstance(quote, dict):
                continue
            if quote.get("quoteType") not in {"EQUITY", "ETF", "MUTUALFUND"}:
                continue
            if quote.get("isYahooFinance") is False:
                continue
            symbol = quote.get("symbol")
            if not isinstance(symbol, str) or not symbol:
                continue
            candidate_name = str(quote.get("longname") or quote.get("shortname") or "")
            candidate_terms = meaningful_name_terms(candidate_name)
            overlap = len(source_terms & candidate_terms)
            coverage = overlap / len(source_terms) if source_terms else 0.0
            similarity = difflib.SequenceMatcher(
                None,
                " ".join(sorted(source_terms)),
                " ".join(sorted(candidate_terms)),
            ).ratio()
            score = max(coverage, similarity) + min(
                float(quote.get("score", 0)) / 1_000_000, 0.05
            )
            is_exact_symbol = (
                security.symbol != security.security_id
                and symbol.upper() == security.symbol.upper()
            )
            if is_exact_symbol and overlap >= 1 and score >= 0.6:
                return symbol
            enough_name_evidence = overlap >= 2 or (
                len(source_terms) == 1 and overlap == 1
            )
            if enough_name_evidence and coverage >= 0.8 and score >= 0.75:
                ranked.append((score, symbol))
        ranked.sort(reverse=True)
        if ranked and (
            len(ranked) == 1 or ranked[0][0] - ranked[1][0] >= 0.1
        ):
            return ranked[0][1]
    return ""


def meaningful_name_terms(name: str) -> set[str]:
    """Normalize security descriptions for conservative name matching."""
    tokens = set(re.findall(r"[A-Z0-9]+", name.upper()))
    return {token for token in tokens if token not in COMPANY_STOP_WORDS and len(token) > 1}


def load_provider_symbols(connection: sqlite3.Connection) -> dict[str, str]:
    """Load previously resolved Yahoo ticker mappings."""
    return {
        security_id: provider_symbol
        for security_id, provider_symbol in connection.execute(
            "SELECT security_id, provider_symbol FROM security_price_symbols "
            "WHERE provider = ?",
            ("Yahoo Finance",),
        )
    }


def fetch_daily_price(provider_symbol: str) -> DailyPrice:
    """Fetch the latest available completed daily close from Yahoo chart API."""
    encoded_symbol = urllib.parse.quote(provider_symbol, safe="")
    utc_today = datetime.now(timezone.utc).date()
    start_date = utc_today - timedelta(days=14)
    query = urllib.parse.urlencode(
        {
            "period1": int(datetime.combine(start_date, datetime.min.time(), timezone.utc).timestamp()),
            "period2": int(datetime.combine(utc_today, datetime.min.time(), timezone.utc).timestamp()),
            "interval": "1d",
        }
    )
    payload = http_json(f"{YAHOO_CHART_URL}/{encoded_symbol}?{query}")
    chart = payload.get("chart", {})
    results = chart.get("result") if isinstance(chart, dict) else None
    if not isinstance(results, list) or not results or not isinstance(results[0], dict):
        raise RuntimeError(f"No chart data returned for {provider_symbol}")
    result = results[0]
    timestamps = result.get("timestamp")
    indicators = result.get("indicators")
    quote_groups = indicators.get("quote") if isinstance(indicators, dict) else None
    quotes = quote_groups[0] if isinstance(quote_groups, list) and quote_groups else {}
    closes = quotes.get("close") if isinstance(quotes, dict) else None
    meta = result.get("meta")
    currency = meta.get("currency") if isinstance(meta, dict) else None
    if not isinstance(timestamps, list) or not isinstance(closes, list):
        raise RuntimeError(f"Incomplete chart response for {provider_symbol}")
    current_market_date = datetime.now(ZoneInfo("America/New_York")).date()
    valid_prices = [
        (timestamp, close)
        for timestamp, close in zip(timestamps, closes, strict=False)
        if isinstance(timestamp, (int, float))
        and isinstance(close, (int, float))
        and datetime.fromtimestamp(timestamp, tz=timezone.utc).date()
        < current_market_date
    ]
    if not valid_prices or not isinstance(currency, str):
        raise RuntimeError(f"No usable daily close/currency for {provider_symbol}")
    timestamp, close = valid_prices[-1]
    price_date = datetime.fromtimestamp(timestamp, tz=timezone.utc).date().isoformat()
    return DailyPrice(price_date, float(close), currency)


def fetch_eur_rate(currency: str, price_date: str) -> tuple[str, float]:
    """Return euros per one source-currency unit using Frankfurter daily FX."""
    if currency == "EUR":
        return price_date, 1.0
    source_currency = "GBP" if currency in {"GBp", "GBX"} else currency.upper()
    minor_unit_divisor = 100 if currency in {"GBp", "GBX"} else 1
    query = urllib.parse.urlencode({"from": source_currency, "to": "EUR"})
    payload = http_json(f"{FRANKFURTER_URL}/{price_date}?{query}")
    rates = payload.get("rates")
    rate = rates.get("EUR") if isinstance(rates, dict) else None
    if not isinstance(rate, (int, float)) or rate <= 0:
        raise RuntimeError(f"No {currency}/EUR rate available for {price_date}")
    fx_date = payload.get("date")
    if not isinstance(fx_date, str):
        raise RuntimeError(f"No FX date returned for {currency}/{price_date}")
    return fx_date, float(rate) / minor_unit_divisor


def fetch_price_record(
    security: Security,
    provider_symbols: dict[str, str],
    fx_rates: dict[tuple[str, str], tuple[str, float]],
) -> PriceRecord:
    """Resolve and fetch one position price and matching dated FX rate."""
    provider_symbol = resolve_provider_symbol(security)
    if not provider_symbol:
        raise RuntimeError(f"Could not confidently map {security.symbol} ({security.security_id})")
    price = fetch_daily_price(provider_symbol)
    rate_key = (price.currency, price.price_date)
    if rate_key not in fx_rates:
        fx_rates[rate_key] = fetch_eur_rate(price.currency, price.price_date)
    fx_date, rate = fx_rates[rate_key]
    return PriceRecord(security, provider_symbol, price, fx_date, rate)


def store_price(connection: sqlite3.Connection, record: PriceRecord) -> None:
    """Insert or refresh one provider price for a security and date."""
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    connection.execute(
        """INSERT INTO security_price_history(
            security_id, symbol, description, provider, provider_symbol,
            price_date, fetched_at, original_price, original_currency,
            fx_date, eur_per_original_unit, price_eur
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(security_id, provider, price_date) DO UPDATE SET
            symbol = excluded.symbol,
            description = excluded.description,
            provider_symbol = excluded.provider_symbol,
            fetched_at = excluded.fetched_at,
            original_price = excluded.original_price,
            original_currency = excluded.original_currency,
            fx_date = excluded.fx_date,
            eur_per_original_unit = excluded.eur_per_original_unit,
            price_eur = excluded.price_eur""",
        (
            record.security.security_id,
            record.security.symbol,
            record.security.description,
            "Yahoo Finance",
            record.provider_symbol,
            record.price.price_date,
            fetched_at,
            record.price.close,
            record.price.currency,
            record.fx_date,
            record.eur_per_original_unit,
            record.price_eur,
        ),
    )
    fx_rates = [(record.price.currency, record.eur_per_original_unit)]
    if record.price.currency in {"GBp", "GBX"}:
        fx_rates.append(("GBP", record.eur_per_original_unit * 100))
    for currency, rate in fx_rates:
        connection.execute(
            """INSERT INTO fx_rate_history(
                currency, rate_date, provider, eur_per_unit, fetched_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(currency, rate_date, provider) DO UPDATE SET
                eur_per_unit = excluded.eur_per_unit,
                fetched_at = excluded.fetched_at""",
            (
                currency,
                record.fx_date,
                "Identity" if currency == "EUR" else "Frankfurter/ECB",
                rate,
                fetched_at,
            ),
        )


def update_database(
    database: Path,
    delay_seconds: float = 0.15,
    requested_symbols: set[str] | None = None,
) -> tuple[int, list[str]]:
    """Fetch prices for all current holdings, keeping successes if some fail."""
    if not database.exists():
        raise FileNotFoundError(
            f"Portfolio database not found at {database}; import statements first"
        )
    succeeded = 0
    failures: list[str] = []
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        existing_tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        if "security_price_history" in existing_tables:
            connection.execute("DROP VIEW IF EXISTS current_security_values_eur")
            connection.execute("DROP VIEW IF EXISTS current_portfolio_value_eur")
            columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(security_price_history)"
                )
            }
            if "fx_date" not in columns:
                connection.execute(
                    "ALTER TABLE security_price_history "
                    "ADD COLUMN fx_date TEXT NOT NULL DEFAULT ''"
                )
                connection.execute(
                    "UPDATE security_price_history SET fx_date = price_date "
                    "WHERE fx_date = ''"
                )
        connection.executescript(PRICE_SCHEMA)
        securities = load_securities(connection)
        if requested_symbols:
            securities = [
                security
                for security in securities
                if security.symbol.upper() in requested_symbols
                or security.security_id.upper() in requested_symbols
            ]
            if not securities:
                raise ValueError(
                    "No positions matched requested symbols: "
                    + ", ".join(sorted(requested_symbols))
                )
        provider_symbols = load_provider_symbols(connection)
        fx_rates: dict[tuple[str, str], tuple[str, float]] = {}
        for index, security in enumerate(securities):
            try:
                stored_provider_symbol = provider_symbols.get(security.security_id)
                record = fetch_price_record(security, provider_symbols, fx_rates)
                if (
                    stored_provider_symbol is not None
                    and stored_provider_symbol != record.provider_symbol
                ):
                    connection.execute(
                        "DELETE FROM security_price_history "
                        "WHERE security_id = ? AND provider = ?",
                        (security.security_id, "Yahoo Finance"),
                    )
                store_price(connection, record)
                if provider_symbols.get(security.security_id) != record.provider_symbol:
                    connection.execute(
                        """INSERT INTO security_price_symbols(
                            security_id, provider, provider_symbol, mapped_at
                        ) VALUES (?, ?, ?, ?)
                        ON CONFLICT(security_id) DO UPDATE SET
                            provider = excluded.provider,
                            provider_symbol = excluded.provider_symbol,
                            mapped_at = excluded.mapped_at""",
                        (
                            security.security_id,
                            "Yahoo Finance",
                            record.provider_symbol,
                            datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        ),
                    )
                    provider_symbols[security.security_id] = record.provider_symbol
                succeeded += 1
                print(
                    f"{security.symbol}: {record.price.close:g} "
                    f"{record.price.currency} = {record.price_eur:.4f} EUR "
                    f"({record.price.price_date}, {record.provider_symbol})"
                )
            except (RuntimeError, ValueError, KeyError, TypeError) as exc:
                failures.append(f"{security.symbol} ({security.security_id}): {exc}")
                print(f"Skipped {security.symbol}: {exc}")
            if index + 1 < len(securities):
                time.sleep(delay_seconds)
    return succeeded, failures


def main(arguments: Sequence[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--delay", type=float, default=0.15)
    parser.add_argument(
        "--symbol", action="append", default=[],
        help="Update only this ticker or security identifier; may be repeated",
    )
    options = parser.parse_args(arguments)
    if options.delay < 0:
        parser.error("--delay must be zero or greater")
    requested_symbols = {symbol.upper() for symbol in options.symbol}
    succeeded, failures = update_database(
        options.database, options.delay, requested_symbols or None
    )
    print(f"Updated prices for {succeeded} securities")
    if failures:
        print(f"Could not update {len(failures)} securities:")
        for failure in failures:
            print(f"- {failure}")
    return 1 if failures and not succeeded else 0


if __name__ == "__main__":
    raise SystemExit(main())
