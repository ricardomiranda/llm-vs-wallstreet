"""Persist sourced issuer-research notes in the local portfolio database."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class ResearchSource:
    """A source consulted during a security review."""

    title: str
    publisher: str
    url: str
    published_at: str | None
    full_text_read: bool


@dataclass(frozen=True)
class SecurityResearchNote:
    """Sourced findings and context recorded for one security review."""

    security_id: str
    symbol: str
    description: str
    summary: str
    findings: list[str]
    limitations: list[str]
    sources: list[ResearchSource]
    urgency_score: int | None = None
    position_value_eur: float | None = None
    researched_at: str | None = None


def _create_research_table(connection: sqlite3.Connection) -> None:
    """Create the append-only security research history table if needed."""
    connection.execute(
        """CREATE TABLE IF NOT EXISTS issuer_research_notes (
               id INTEGER PRIMARY KEY,
               security_id TEXT NOT NULL,
               symbol TEXT NOT NULL,
               description TEXT NOT NULL,
               researched_at TEXT NOT NULL,
               urgency_score INTEGER CHECK (
                   urgency_score IS NULL OR urgency_score BETWEEN 0 AND 5
               ),
               position_value_eur REAL,
               summary TEXT NOT NULL,
               findings_json TEXT NOT NULL,
               limitations_json TEXT NOT NULL,
               sources_json TEXT NOT NULL
           )"""
    )
    connection.execute(
        """CREATE INDEX IF NOT EXISTS issuer_research_notes_security_date
           ON issuer_research_notes(security_id, researched_at DESC, id DESC)"""
    )


def save_security_research_note(
    database: Path, note: SecurityResearchNote
) -> str:
    """Append a security research note and return its UTC timestamp."""
    if not database.is_file():
        raise FileNotFoundError(f"Portfolio database not found: {database}")
    if not note.security_id.strip() or not note.summary.strip():
        raise ValueError("A security ID and a non-empty research summary are required")
    if note.urgency_score is not None and not 0 <= note.urgency_score <= 5:
        raise ValueError("Urgency score must be between 0 and 5")
    if any(not source.url.startswith("https://") for source in note.sources):
        raise ValueError("Research source URLs must use HTTPS")

    researched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with sqlite3.connect(database) as connection:
        snapshots = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='snapshots'"
        ).fetchone()
        if snapshots is None:
            raise RuntimeError("Portfolio database has no imported snapshots table")
        security_exists = connection.execute(
            "SELECT 1 FROM positions WHERE security_id = ? LIMIT 1",
            (note.security_id,),
        ).fetchone()
        if security_exists is None:
            raise ValueError(
                f"Security ID {note.security_id!r} does not exist in imported positions"
            )
        _create_research_table(connection)
        connection.execute(
            """INSERT INTO issuer_research_notes(
                   security_id, symbol, description, researched_at, urgency_score,
                   position_value_eur, summary, findings_json, limitations_json,
                   sources_json
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                note.security_id,
                note.symbol,
                note.description,
                researched_at,
                note.urgency_score,
                note.position_value_eur,
                note.summary,
                json.dumps(note.findings, ensure_ascii=False),
                json.dumps(note.limitations, ensure_ascii=False),
                json.dumps(
                    [
                        {
                            "title": source.title,
                            "publisher": source.publisher,
                            "url": source.url,
                            "published_at": source.published_at,
                            "full_text_read": source.full_text_read,
                        }
                        for source in note.sources
                    ],
                    ensure_ascii=False,
                ),
            ),
        )
    return researched_at


def load_security_research_notes(
    database: Path, security_id: str, limit: int = 20
) -> list[SecurityResearchNote]:
    """Load the most recent saved research notes for a security."""
    if not database.is_file():
        return []
    with sqlite3.connect(database) as connection:
        table_exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='issuer_research_notes'"
        ).fetchone()
        if table_exists is None:
            return []
        rows = connection.execute(
            """SELECT security_id, symbol, description, researched_at,
                      urgency_score, position_value_eur, summary, findings_json,
                      limitations_json, sources_json
               FROM issuer_research_notes
               WHERE security_id = ?
               ORDER BY researched_at DESC, id DESC
               LIMIT ?""",
            (security_id, limit),
        ).fetchall()

    notes: list[SecurityResearchNote] = []
    for row in rows:
        sources = [
            ResearchSource(
                title=str(source.get("title") or "Untitled source"),
                publisher=str(source.get("publisher") or "Unknown publisher"),
                url=str(source.get("url") or ""),
                published_at=(
                    str(source["published_at"])
                    if source.get("published_at") is not None else None
                ),
                full_text_read=bool(source.get("full_text_read", False)),
            )
            for source in json.loads(row[9])
            if isinstance(source, dict)
        ]
        notes.append(
            SecurityResearchNote(
                security_id=str(row[0]),
                symbol=str(row[1]),
                description=str(row[2]),
                researched_at=str(row[3]),
                urgency_score=int(row[4]) if row[4] is not None else None,
                position_value_eur=(
                    float(row[5]) if row[5] is not None else None
                ),
                summary=str(row[6]),
                findings=[str(item) for item in json.loads(row[7])],
                limitations=[str(item) for item in json.loads(row[8])],
                sources=sources,
            )
        )
    return notes
