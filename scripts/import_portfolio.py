"""Import timestamped brokerage statements into a local SQLite database."""

from __future__ import annotations

import argparse
import csv
import re
import sqlite3
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[1]
REFERENCES = ROOT / "references"
DEFAULT_DATABASE = ROOT / "output" / "portfolio.sqlite3"
SPREADSHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
SPREADSHEET_TAG = f"{{{SPREADSHEET_NS}}}"
FILENAME_PATTERN = re.compile(
    r"(?P<date>\d{8})\.(?P<broker>degiro|interactive-brokers)\.(?P<extension>xlsx|csv)"
)


@dataclass
class Position:
    """One reported security holding in a broker snapshot."""

    security_id: str
    symbol: str
    description: str
    asset_type: str
    currency: str
    quantity: float
    unit_price: float | None
    market_value: float
    market_value_base: float | None
    cost_basis: float | None = None
    unrealized_pl: float | None = None


@dataclass
class CashBalance:
    """A cash balance reported by a broker."""

    currency: str
    amount: float
    amount_base: float | None
    settled_amount: float | None = None


@dataclass
class Snapshot:
    """The normalized contents of one source statement."""

    broker: str
    as_of_date: str
    source_file: str
    base_currency: str
    total_value_base: float | None
    generated_at: str | None = None
    positions: list[Position] = field(default_factory=list)
    cash_balances: list[CashBalance] = field(default_factory=list)
    fx_rates: dict[str, float] = field(default_factory=dict)


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY,
    broker TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    as_of_date TEXT NOT NULL,
    generated_at TEXT,
    source_file TEXT NOT NULL,
    base_currency TEXT NOT NULL,
    total_value_base REAL,
    UNIQUE(account_id, source_file)
);
CREATE TABLE IF NOT EXISTS positions (
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    security_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    description TEXT NOT NULL,
    asset_type TEXT NOT NULL,
    currency TEXT NOT NULL,
    quantity REAL NOT NULL,
    unit_price REAL,
    market_value REAL NOT NULL,
    market_value_base REAL,
    cost_basis REAL,
    unrealized_pl REAL,
    PRIMARY KEY(snapshot_id, security_id, currency)
);
CREATE TABLE IF NOT EXISTS cash_balances (
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    currency TEXT NOT NULL,
    amount REAL NOT NULL,
    amount_base REAL,
    settled_amount REAL,
    PRIMARY KEY(snapshot_id, currency)
);
CREATE TABLE IF NOT EXISTS fx_rates (
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    currency TEXT NOT NULL,
    rate_to_base REAL NOT NULL,
    PRIMARY KEY(snapshot_id, currency)
);
CREATE TABLE IF NOT EXISTS position_limits (
    security_id TEXT PRIMARY KEY,
    max_value REAL,
    currency TEXT,
    max_portfolio_pct REAL,
    notes TEXT,
    CHECK (max_value IS NULL OR max_value >= 0),
    CHECK (max_portfolio_pct IS NULL OR
           (max_portfolio_pct >= 0 AND max_portfolio_pct <= 100))
);
CREATE INDEX IF NOT EXISTS idx_snapshots_as_of_date
    ON snapshots(as_of_date);
CREATE INDEX IF NOT EXISTS idx_positions_security_id
    ON positions(security_id);
CREATE VIEW IF NOT EXISTS position_exposures AS
SELECT
    s.id AS snapshot_id,
    a.broker,
    s.as_of_date,
    p.security_id,
    MAX(p.symbol) AS symbol,
    MAX(p.description) AS description,
    s.base_currency,
    SUM(p.market_value_base) AS market_value_base,
    s.total_value_base,
    100.0 * SUM(p.market_value_base) / NULLIF(s.total_value_base, 0)
        AS portfolio_pct
FROM positions AS p
JOIN snapshots AS s ON s.id = p.snapshot_id
JOIN accounts AS a ON a.id = s.account_id
GROUP BY s.id, p.security_id;
CREATE VIEW IF NOT EXISTS position_limit_alerts AS
SELECT
    e.*,
    l.max_value,
    l.currency AS limit_currency,
    l.max_portfolio_pct,
    CASE
        WHEN l.max_value IS NOT NULL AND l.currency = e.base_currency
             AND e.market_value_base > l.max_value THEN 1
        ELSE 0
    END AS exceeds_max_value,
    CASE
        WHEN l.max_portfolio_pct IS NOT NULL
             AND e.portfolio_pct > l.max_portfolio_pct THEN 1
        ELSE 0
    END AS exceeds_max_portfolio_pct
FROM position_exposures AS e
JOIN position_limits AS l ON l.security_id = e.security_id
WHERE (l.max_value IS NOT NULL AND l.currency = e.base_currency
       AND e.market_value_base > l.max_value)
   OR (l.max_portfolio_pct IS NOT NULL
       AND e.portfolio_pct > l.max_portfolio_pct);
"""


def parse_number(value: str | None) -> float | None:
    """Parse broker-formatted numbers, leaving blank values as None."""
    if value is None:
        return None
    normalized = value.strip().replace(",", "")
    if not normalized:
        return None
    if normalized.endswith("%"):
        normalized = normalized[:-1]
    return float(normalized)


def xlsx_cell_value(cell: ElementTree.Element, shared_strings: list[str]) -> str:
    """Return the textual value of an XLSX cell without external libraries."""
    cell_type = cell.get("t")
    value_element = cell.find(f"{SPREADSHEET_TAG}v")
    if cell_type == "inlineStr":
        inline = cell.find(f"{SPREADSHEET_TAG}is")
        if inline is None:
            return ""
        return "".join(
            text.text or "" for text in inline.iter(f"{SPREADSHEET_TAG}t")
        )
    if value_element is None or value_element.text is None:
        return ""
    if cell_type == "s":
        return shared_strings[int(value_element.text)]
    return value_element.text


def read_degiro(path: Path, as_of_date: str) -> Snapshot:
    """Read the tabular holdings and EUR valuations in a DeGiro XLSX file."""
    with zipfile.ZipFile(path) as workbook:
        strings_root = ElementTree.fromstring(workbook.read("xl/sharedStrings.xml"))
        shared_strings = [
            "".join(text.text or "" for text in item.iter(f"{SPREADSHEET_TAG}t"))
            for item in strings_root.findall(f"{SPREADSHEET_TAG}si")
        ]
        sheet_root = ElementTree.fromstring(
            workbook.read("xl/worksheets/sheet1.xml")
        )

    snapshot = Snapshot(
        broker="DeGiro",
        as_of_date=as_of_date,
        source_file=path.name,
        base_currency="EUR",
        total_value_base=0.0,
        fx_rates={"EUR": 1.0},
    )
    for row in sheet_root.iter(f"{SPREADSHEET_TAG}row"):
        cells = {
            re.sub(r"\d+", "", cell.get("r", "")): xlsx_cell_value(
                cell, shared_strings
            )
            for cell in row.findall(f"{SPREADSHEET_TAG}c")
        }
        product = cells.get("A", "").strip()
        if not product or product == "Produto":
            continue
        currency = cells.get("E", "").strip()
        if product.startswith("CASH &"):
            amount = parse_number(cells.get("F")) or 0.0
            amount_base = parse_number(cells.get("G"))
            snapshot.cash_balances.append(
                CashBalance(currency, amount, amount_base)
            )
            if amount_base is not None:
                snapshot.total_value_base = (snapshot.total_value_base or 0.0) + amount_base
            continue

        identifier = cells.get("B", "").strip()
        quantity = parse_number(cells.get("C"))
        unit_price = parse_number(cells.get("D"))
        market_value = parse_number(cells.get("F"))
        market_value_base = parse_number(cells.get("G"))
        if not identifier or quantity is None or market_value is None:
            continue
        snapshot.positions.append(
            Position(
                security_id=identifier,
                symbol=identifier,
                description=product,
                asset_type="security",
                currency=currency,
                quantity=quantity,
                unit_price=unit_price,
                market_value=market_value,
                market_value_base=market_value_base,
            )
        )
        if market_value_base is not None:
            snapshot.total_value_base = (snapshot.total_value_base or 0.0) + market_value_base
    return snapshot


def read_interactive_brokers(path: Path, as_of_date: str) -> Snapshot:
    """Read key account values and open positions from an IB activity CSV."""
    rows: list[list[str]] = []
    with path.open(newline="", encoding="utf-8-sig") as source:
        rows.extend(csv.reader(source))

    base_currency = "USD"
    total_value: float | None = None
    generated_at: str | None = None
    period_date: str | None = None
    ending_cash: dict[str, float] = {}
    settled_cash: dict[str, float] = {}
    fx_rates: dict[str, float] = {base_currency: 1.0}
    instrument_info: dict[str, tuple[str, str, str]] = {}
    snapshot = Snapshot(
        broker="Interactive Brokers",
        as_of_date=as_of_date,
        source_file=path.name,
        base_currency=base_currency,
        total_value_base=None,
    )

    for row in rows:
        if len(row) < 3:
            continue
        section, row_type = row[0], row[1]
        if section == "Statement" and row_type == "Data" and len(row) >= 4:
            if row[2] == "WhenGenerated":
                generated_at = row[3]
            elif row[2] == "Period":
                period_date = row[3]
        if section == "Account Information" and row_type == "Data" and len(row) >= 4:
            if row[2] == "Base Currency":
                base_currency = row[3]
                fx_rates[base_currency] = 1.0
        if section == "Base Currency Exchange Rate" and row_type == "Data" and len(row) >= 4:
            rate = parse_number(row[3])
            if rate is not None:
                fx_rates[row[2]] = rate
        if section == "Financial Instrument Information" and row_type == "Data" and len(row) >= 12:
            symbol = row[3]
            instrument_info[symbol] = (row[4], row[6], row[10])
        if section == "Net Asset Value" and row_type == "Data" and len(row) >= 7:
            if row[2].strip() == "Total":
                total_value = parse_number(row[6])
        if section == "Cash Report" and row_type == "Data" and len(row) >= 5:
            currency = row[3].strip()
            if currency != "Base Currency Summary":
                if row[2] == "Ending Cash":
                    amount = parse_number(row[4])
                    if amount is not None:
                        ending_cash[currency] = amount
                elif row[2] == "Ending Settled Cash":
                    amount = parse_number(row[4])
                    if amount is not None:
                        settled_cash[currency] = amount
        if section == "Open Positions" and row_type == "Data" and len(row) >= 13:
            if row[2] != "Summary":
                continue
            asset_type = row[3]
            currency = row[4]
            symbol = row[5]
            quantity = parse_number(row[6])
            cost_basis = parse_number(row[9])
            unit_price = parse_number(row[10])
            market_value = parse_number(row[11])
            unrealized_pl = parse_number(row[12])
            if quantity is None or market_value is None:
                continue
            rate = fx_rates.get(currency)
            description, security_id, info_asset_type = instrument_info.get(
                symbol, (symbol, symbol, asset_type)
            )
            snapshot.positions.append(
                Position(
                    security_id=security_id or symbol,
                    symbol=symbol,
                    description=description,
                    asset_type=info_asset_type or asset_type,
                    currency=currency,
                    quantity=quantity,
                    unit_price=unit_price,
                    market_value=market_value,
                    market_value_base=(market_value * rate if rate is not None else None),
                    cost_basis=cost_basis,
                    unrealized_pl=unrealized_pl,
                )
            )

    # Financial instrument metadata and FX tables follow Open Positions in the
    # broker export, so resolve them in a second pass after collecting all rows.
    info_rows = {
        row[3]: (row[4], row[6], row[10])
        for row in rows
        if len(row) >= 12
        and row[0] == "Financial Instrument Information"
        and row[1] == "Data"
    }
    fx_rates = {
        row[2]: rate
        for row in rows
        if len(row) >= 4
        and row[0] == "Base Currency Exchange Rate"
        and row[1] == "Data"
        and (rate := parse_number(row[3])) is not None
    }
    fx_rates[base_currency] = 1.0
    for position in snapshot.positions:
        description, security_id, info_asset_type = info_rows.get(
            position.symbol, (position.symbol, position.symbol, position.asset_type)
        )
        position.description = description
        position.security_id = security_id or position.symbol
        position.asset_type = info_asset_type or position.asset_type
        rate = fx_rates.get(position.currency)
        position.market_value_base = (
            position.market_value * rate if rate is not None else None
        )

    snapshot.base_currency = base_currency
    snapshot.total_value_base = total_value
    snapshot.generated_at = generated_at
    snapshot.fx_rates = fx_rates
    for currency, amount in ending_cash.items():
        rate = fx_rates.get(currency)
        snapshot.cash_balances.append(
            CashBalance(
                currency=currency,
                amount=amount,
                amount_base=amount * rate if rate is not None else None,
                settled_amount=settled_cash.get(currency),
            )
        )
    if period_date:
        parsed_period = re.search(r"([A-Z][a-z]{2})\s+(\d{1,2}),\s+(\d{4})", period_date)
        if parsed_period:
            month_names = {
                "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04",
                "May": "05", "Jun": "06", "Jul": "07", "Aug": "08",
                "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12",
            }
            statement_date = (
                f"{parsed_period.group(3)}-{month_names[parsed_period.group(1)]}-"
                f"{int(parsed_period.group(2)):02d}"
            )
            if statement_date != as_of_date:
                raise ValueError(
                    f"Filename date {as_of_date} does not match statement period {statement_date}"
                )
    return snapshot


def import_snapshot(connection: sqlite3.Connection, snapshot: Snapshot) -> bool:
    """Insert or refresh a source file while preserving other snapshots."""
    account_row = connection.execute(
        "INSERT INTO accounts(broker) VALUES (?) "
        "ON CONFLICT(broker) DO UPDATE SET broker = excluded.broker "
        "RETURNING id",
        (snapshot.broker,),
    ).fetchone()
    if account_row is None:
        raise RuntimeError(f"Could not register account for {snapshot.broker}")
    existing = connection.execute(
        "SELECT id FROM snapshots WHERE account_id = ? AND source_file = ?",
        (account_row[0], snapshot.source_file),
    ).fetchone()
    if existing is None:
        cursor = connection.execute(
            """INSERT INTO snapshots(
                account_id, as_of_date, generated_at, source_file,
                base_currency, total_value_base
            ) VALUES (?, ?, ?, ?, ?, ?)""",
            (
                account_row[0], snapshot.as_of_date, snapshot.generated_at,
                snapshot.source_file, snapshot.base_currency, snapshot.total_value_base,
            ),
        )
        snapshot_id = cursor.lastrowid
    else:
        snapshot_id = int(existing[0])
        connection.execute(
            """UPDATE snapshots SET as_of_date = ?, generated_at = ?,
                base_currency = ?, total_value_base = ? WHERE id = ?""",
            (
                snapshot.as_of_date, snapshot.generated_at, snapshot.base_currency,
                snapshot.total_value_base, snapshot_id,
            ),
        )
        for table in ("positions", "cash_balances", "fx_rates"):
            connection.execute(
                f"DELETE FROM {table} WHERE snapshot_id = ?", (snapshot_id,)
            )
    connection.executemany(
        """INSERT INTO positions(
            snapshot_id, security_id, symbol, description, asset_type, currency,
            quantity, unit_price, market_value, market_value_base, cost_basis,
            unrealized_pl
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (
                snapshot_id, position.security_id, position.symbol,
                position.description, position.asset_type, position.currency,
                position.quantity, position.unit_price, position.market_value,
                position.market_value_base, position.cost_basis,
                position.unrealized_pl,
            )
            for position in snapshot.positions
        ],
    )
    connection.executemany(
        """INSERT INTO cash_balances(
            snapshot_id, currency, amount, amount_base, settled_amount
        ) VALUES (?, ?, ?, ?, ?)""",
        [
            (snapshot_id, balance.currency, balance.amount, balance.amount_base,
             balance.settled_amount)
            for balance in snapshot.cash_balances
        ],
    )
    connection.executemany(
        "INSERT INTO fx_rates(snapshot_id, currency, rate_to_base) VALUES (?, ?, ?)",
        [(snapshot_id, currency, rate) for currency, rate in snapshot.fx_rates.items()],
    )
    return existing is None


def discover_snapshots(references: Path) -> list[Snapshot]:
    """Parse all supported timestamped statement files in date order."""
    snapshots: list[Snapshot] = []
    for path in sorted(references.iterdir()):
        match = FILENAME_PATTERN.fullmatch(path.name)
        if match is None:
            continue
        date_parts = match.group("date")
        as_of_date = f"{date_parts[:4]}-{date_parts[4:6]}-{date_parts[6:8]}"
        if match.group("broker") == "degiro":
            snapshots.append(read_degiro(path, as_of_date))
        else:
            snapshots.append(read_interactive_brokers(path, as_of_date))
    return snapshots


def run(database: Path, references: Path) -> int:
    """Initialize the schema and import new snapshots."""
    database.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database) as connection:
        connection.executescript(SCHEMA)
        inserted = 0
        for snapshot in discover_snapshots(references):
            if import_snapshot(connection, snapshot):
                inserted += 1
                print(
                    f"Imported {snapshot.source_file}: {len(snapshot.positions)} positions, "
                    f"as of {snapshot.as_of_date}"
                )
            else:
                print(f"Refreshed snapshot {snapshot.source_file}")
    return inserted


def main(arguments: Sequence[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database", type=Path, default=DEFAULT_DATABASE,
        help=f"SQLite destination (default: {DEFAULT_DATABASE.relative_to(ROOT)})",
    )
    parser.add_argument(
        "--references", type=Path, default=REFERENCES,
        help="Directory containing timestamped broker statements",
    )
    options = parser.parse_args(arguments)
    inserted = run(options.database, options.references)
    print(f"Imported {inserted} new snapshot(s) into {options.database}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
