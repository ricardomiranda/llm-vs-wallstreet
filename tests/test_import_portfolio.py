"""Behavioral tests for broker statement parsing and snapshot imports."""

from __future__ import annotations

import csv
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from import_portfolio import (
    SCHEMA,
    CashBalance,
    Position,
    Snapshot,
    discover_statement_files,
    import_snapshot,
    main,
    parse_number,
    read_degiro,
    read_interactive_brokers,
    run,
    xlsx_cell_value,
)


def self_snapshot(source_file: str) -> Snapshot:
    """Build a small deterministic snapshot for importer entry-point tests."""
    return Snapshot("Interactive Brokers", "2026-11-07", source_file, "USD", 10.0)


class StatementParsingTests(unittest.TestCase):
    """Cover normalized values and IB CSV metadata reconciliation."""

    def test_parse_number_handles_empty_commas_and_percent(self) -> None:
        self.assertIsNone(parse_number(None))
        self.assertIsNone(parse_number("  "))
        self.assertEqual(parse_number("1,234.50"), 1234.5)
        self.assertEqual(parse_number("-12.5%"), -12.5)

    def test_xlsx_cell_values_handle_shared_inline_and_empty_cells(self) -> None:
        shared = ElementTree.fromstring(
            '<c xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            't="s"><v>1</v></c>'
        )
        inline = ElementTree.fromstring(
            '<c xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            't="inlineStr"><is><r><t>hello</t></r><r><t> world</t></r></is></c>'
        )
        missing_inline = ElementTree.fromstring(
            '<c xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            't="inlineStr"/>'
        )
        numeric = ElementTree.fromstring(
            '<c xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<v>42</v></c>'
        )
        empty = ElementTree.fromstring(
            '<c xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<v/></c>'
        )
        self.assertEqual(xlsx_cell_value(shared, ["zero", "one"]), "one")
        self.assertEqual(xlsx_cell_value(inline, []), "hello world")
        self.assertEqual(xlsx_cell_value(missing_inline, []), "")
        self.assertEqual(xlsx_cell_value(numeric, []), "42")
        self.assertEqual(xlsx_cell_value(empty, []), "")

    def test_interactive_brokers_import_resolves_later_metadata_and_fx(self) -> None:
        rows = [
            ["Statement", "Data", "WhenGenerated", "2026-11-07"],
            ["Statement", "Data", "Period", "November 7, 2026"],
            ["Account Information", "Data", "Base Currency", "USD"],
            ["Open Positions", "Data", "Summary", "STK", "EUR", "ABC", "10", "", "", "1000", "100", "900", "-100"],
            ["Cash Report", "Data", "Ending Cash", "EUR", "50"],
            ["Cash Report", "Data", "Ending Settled Cash", "EUR", "40"],
            ["Financial Instrument Information", "Data", "", "ABC", "Acme Corp", "", "US0000000001", "", "", "", "STK", ""],
            ["Base Currency Exchange Rate", "Data", "EUR", "1.1"],
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "20261107.interactive-brokers.csv"
            with path.open("w", encoding="utf-8", newline="") as output:
                csv.writer(output).writerows(rows)
            snapshot = read_interactive_brokers(path, "2026-11-07")

        self.assertEqual(snapshot.broker, "Interactive Brokers")
        self.assertEqual(snapshot.generated_at, "2026-11-07")
        self.assertIsNone(snapshot.total_value_base)  # No NAV Total row.
        self.assertEqual(snapshot.fx_rates, {"EUR": 1.1, "USD": 1.0})
        self.assertEqual(snapshot.positions[0].security_id, "US0000000001")
        self.assertEqual(snapshot.positions[0].description, "Acme Corp")
        self.assertAlmostEqual(snapshot.positions[0].market_value_base or 0, 990.0)
        self.assertEqual(snapshot.positions[0].unrealized_pl, -100.0)
        self.assertEqual(snapshot.cash_balances[0].currency, "EUR")
        self.assertEqual(snapshot.cash_balances[0].amount, 50.0)
        self.assertAlmostEqual(snapshot.cash_balances[0].amount_base or 0, 55.0)
        self.assertEqual(snapshot.cash_balances[0].settled_amount, 40.0)

    def test_interactive_brokers_rejects_filename_period_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "statement.csv"
            path.write_text(
                'Statement,Data,Period,"Oct 1, 2026"\n', encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "does not match"):
                read_interactive_brokers(path, "2026-11-07")

    def test_degiro_reads_tabular_workbook_rows(self) -> None:
        import zipfile

        strings = ["Product", "Produto", "CASH & EUR", "EUR", "ABC123", "Acme"]
        string_items = [
            "<si><t>Product</t></si>", "<si><t>Produto</t></si>",
            "<si><t>CASH &amp; EUR</t></si>", "<si><t>EUR</t></si>",
            "<si><t>ABC123</t></si>", "<si><t>Acme</t></si>",
        ]
        shared_xml = (
            '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            + "".join(string_items)
            + "</sst>"
        )
        sheet_xml = """<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>
          <row><c r="A1" t="s"><v>1</v></c></row>
          <row><c r="A2" t="s"><v>2</v></c><c r="E2" t="s"><v>3</v></c><c r="F2"><v>10</v></c><c r="G2"><v>10</v></c></row>
          <row><c r="A3" t="s"><v>0</v></c><c r="B3" t="s"><v>4</v></c><c r="C3"><v>2</v></c><c r="D3"><v>5</v></c><c r="E3" t="s"><v>3</v></c><c r="F3"><v>20</v></c><c r="G3"><v>20</v></c></row>
          <row><c r="A4" t="s"><v>5</v></c><c r="B4" t="s"><v>4</v></c></row>
        </sheetData></worksheet>"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "statement.xlsx"
            with zipfile.ZipFile(path, "w") as workbook:
                workbook.writestr("xl/sharedStrings.xml", shared_xml)
                workbook.writestr("xl/worksheets/sheet1.xml", sheet_xml)
            snapshot = read_degiro(path, "2026-11-07")
        self.assertEqual(snapshot.positions[0].security_id, "ABC123")
        self.assertEqual(snapshot.positions[0].description, "Product")
        self.assertEqual(snapshot.total_value_base, 30.0)
        self.assertEqual(snapshot.cash_balances[0].amount, 10.0)

    def test_main_imports_supported_file_into_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            references = root / "references"
            references.mkdir()
            statement = references / "20261107.interactive-brokers.csv"
            statement.write_text("Statement,Data,Period,\"Nov 7, 2026\"\n", encoding="utf-8")
            database = root / "portfolio.sqlite3"
            with patch("import_portfolio.read_interactive_brokers", return_value=self_snapshot(statement.name)):
                self.assertEqual(main(["--database", str(database), "--references", str(references)]), 0)
            with sqlite3.connect(database) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0], 1)

    def test_main_check_mode_prints_new_file_count(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            references = root / "references"
            references.mkdir()
            (references / "20261107.degiro.xlsx").touch()
            with patch("builtins.print") as output:
                self.assertEqual(main(["--check", "--database", str(root / "db.sqlite"), "--references", str(references)]), 0)
            self.assertIn("Found 1 new", output.call_args.args[0])


class SnapshotImportTests(unittest.TestCase):
    """Verify insert/refresh behavior and file discovery/check mode."""

    def make_snapshot(self) -> Snapshot:
        return Snapshot(
            broker="Test Broker",
            as_of_date="2026-11-07",
            source_file="statement.csv",
            base_currency="EUR",
            total_value_base=125.0,
            positions=[
                Position("ID", "SYM", "Company", "stock", "EUR", 1, 100, 100, 100)
            ],
            cash_balances=[CashBalance("EUR", 25, 25)],
            fx_rates={"EUR": 1.0},
        )

    def test_import_snapshot_inserts_then_refreshes_same_source(self) -> None:
        with sqlite3.connect(":memory:") as connection:
            connection.executescript(SCHEMA)
            snapshot = self.make_snapshot()
            self.assertTrue(import_snapshot(connection, snapshot))
            self.assertFalse(import_snapshot(connection, snapshot))
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM positions").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM cash_balances").fetchone()[0], 1)

    def test_discovery_ignores_unsupported_files_and_formats_date(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "20261107.degiro.xlsx").touch()
            (root / "notes.txt").touch()
            (root / "20261108.interactive-brokers.csv").touch()
            found = discover_statement_files(root)
        self.assertEqual([item[1:] for item in found], [
            ("degiro", "2026-11-07"), ("interactive-brokers", "2026-11-08")
        ])

    def test_check_mode_reports_files_without_creating_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            references = root / "references"
            references.mkdir()
            database = root / "nested" / "portfolio.sqlite3"
            (references / "20261107.degiro.xlsx").touch()
            self.assertEqual(run(database, references, check_only=True), 1)
            self.assertFalse(database.exists())
            self.assertEqual(run(database, references, check_only=True), 1)

    def test_check_mode_reports_no_supported_statements(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            references = root / "references"
            references.mkdir()
            self.assertEqual(run(root / "portfolio.sqlite3", references, check_only=True), 0)


if __name__ == "__main__":
    unittest.main()
