"""Tests for validated issuer research notes and local persistence."""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from record_security_research import main, parse_research_note
from security_research_notes import (
    ResearchSource,
    SecurityResearchNote,
    load_security_research_notes,
    save_security_research_note,
)


def note_payload() -> dict[str, object]:
    """Return a valid, representative JSON payload."""
    return {
        "security_id": "ID-1",
        "symbol": "ABC",
        "description": "Example Corp",
        "summary": " Evidence-based summary ",
        "findings": [" growth ", "", "risk"],
        "limitations": ["limited data"],
        "sources": [{
            "title": "Annual report",
            "publisher": "Issuer",
            "url": "https://example.test/report",
            "published_at": None,
            "full_text_read": True,
        }],
        "urgency_score": 3,
        "position_value_eur": 12,
        "recommendation_impact": "No change",
    }


class ResearchNoteValidationTests(unittest.TestCase):
    """Reject malformed values and normalize valid research payloads."""

    def test_parse_normalizes_optional_fields_and_source(self) -> None:
        note = parse_research_note(note_payload())
        self.assertEqual(note.summary, "Evidence-based summary")
        self.assertEqual(note.findings, ["growth", "risk"])
        self.assertEqual(note.position_value_eur, 12.0)
        self.assertEqual(note.sources[0].publisher, "Issuer")
        self.assertTrue(note.sources[0].full_text_read)
        self.assertEqual(note.recommendation_impact, "No change")

    def test_parse_requires_object_text_and_string_lists(self) -> None:
        with self.assertRaisesRegex(ValueError, "JSON object"):
            parse_research_note([])
        for field in ("security_id", "symbol", "description", "summary"):
            payload = note_payload()
            payload[field] = " "
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, field):
                parse_research_note(payload)
        payload = note_payload()
        payload["findings"] = [1]
        with self.assertRaisesRegex(ValueError, "list of strings"):
            parse_research_note(payload)

    def test_parse_checks_numbers_and_source_shapes(self) -> None:
        for field, invalid in (("urgency_score", True), ("position_value_eur", False)):
            payload = note_payload()
            payload[field] = invalid
            with self.subTest(field=field), self.assertRaises(ValueError):
                parse_research_note(payload)
        invalid_sources: list[object] = ["not an object", {"title": 3}]
        for source in invalid_sources:
            payload = note_payload()
            payload["sources"] = [source]
            with self.subTest(source=source), self.assertRaises(ValueError):
                parse_research_note(payload)
        for field, value in (("published_at", 3), ("full_text_read", "yes")):
            payload = note_payload()
            source = dict(payload["sources"][0])  # type: ignore[index]
            source[field] = value
            payload["sources"] = [source]
            with self.subTest(field=field), self.assertRaises(ValueError):
                parse_research_note(payload)


class ResearchNotePersistenceTests(unittest.TestCase):
    """Verify append-only note storage, schema migration, and loading."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name) / "portfolio.sqlite3"
        with sqlite3.connect(self.database) as connection:
            connection.executescript(
                "CREATE TABLE snapshots(id INTEGER PRIMARY KEY);"
                "CREATE TABLE positions(security_id TEXT NOT NULL);"
                "INSERT INTO snapshots VALUES (1);"
                "INSERT INTO positions VALUES ('ID-1');"
            )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def make_note(self, **overrides: object) -> SecurityResearchNote:
        fields: dict[str, object] = {
            "security_id": "ID-1", "symbol": "ABC", "description": "Example",
            "summary": "Summary", "findings": ["finding"],
            "limitations": ["limit"],
            "sources": [ResearchSource("Report", "Issuer", "https://example.test", None, True)],
            "urgency_score": 2, "position_value_eur": 50.0,
            "recommendation_impact": "unchanged",
        }
        fields.update(overrides)
        return SecurityResearchNote(**fields)  # type: ignore[arg-type]

    def test_save_and_load_round_trip_and_limit(self) -> None:
        save_security_research_note(self.database, self.make_note())
        save_security_research_note(self.database, self.make_note(summary="Second"))
        notes = load_security_research_notes(self.database, "ID-1", limit=1)
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0].summary, "Second")
        self.assertEqual(notes[0].recommendation_impact, "unchanged")
        self.assertEqual(notes[0].sources[0].url, "https://example.test")
        self.assertEqual(load_security_research_notes(self.database, "missing"), [])

    def test_save_rejects_invalid_note_and_missing_snapshot_schema(self) -> None:
        for note, message in (
            (self.make_note(security_id=" "), "security ID"),
            (self.make_note(summary=" "), "summary"),
            (self.make_note(urgency_score=6), "Urgency score"),
            (self.make_note(sources=[ResearchSource("x", "y", "http://bad", None, False)]), "HTTPS"),
            (self.make_note(security_id="unknown"), "does not exist"),
        ):
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                save_security_research_note(self.database, note)
        empty_database = Path(self.temporary.name) / "empty.sqlite3"
        sqlite3.connect(empty_database).close()
        with self.assertRaisesRegex(RuntimeError, "snapshots table"):
            save_security_research_note(empty_database, self.make_note())
        self.assertEqual(load_security_research_notes(empty_database, "ID-1"), [])
        self.assertEqual(load_security_research_notes(Path(self.temporary.name) / "absent", "ID-1"), [])

    def test_loader_supports_legacy_schema_without_impact_column(self) -> None:
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                """CREATE TABLE issuer_research_notes (
                   id INTEGER PRIMARY KEY, security_id TEXT, symbol TEXT,
                   description TEXT, researched_at TEXT, urgency_score INTEGER,
                   position_value_eur REAL, summary TEXT, findings_json TEXT,
                   limitations_json TEXT, sources_json TEXT)"""
            )
            connection.execute(
                "INSERT INTO issuer_research_notes VALUES (1,'ID-1','ABC','Example',"
                "'2026-01-01',NULL,NULL,'Old','[]','[]','[{},3]')"
            )
        note = load_security_research_notes(self.database, "ID-1")[0]
        self.assertIsNone(note.recommendation_impact)
        self.assertEqual(note.sources[0].title, "Untitled source")
        self.assertEqual(note.sources[0].publisher, "Unknown publisher")

    def test_command_saves_stdin_payload(self) -> None:
        payload = json.dumps(note_payload())
        with patch("sys.stdin") as standard_input:
            standard_input.read.return_value = payload
            standard_input.__iter__.return_value = iter([payload])
            self.assertEqual(main(["--database", str(self.database)]), 0)
        self.assertEqual(len(load_security_research_notes(self.database, "ID-1")), 1)


if __name__ == "__main__":
    unittest.main()
