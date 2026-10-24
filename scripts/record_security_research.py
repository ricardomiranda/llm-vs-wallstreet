"""Read a research-note JSON document from stdin and save it locally."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Sequence

from import_portfolio import DEFAULT_DATABASE
from security_research_notes import ResearchSource, SecurityResearchNote
from security_research_notes import save_security_research_note


def _required_text(payload: dict[str, Any], field: str) -> str:
    """Return a required non-empty text field."""
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"'{field}' must be a non-empty string")
    return value.strip()


def _text_list(payload: dict[str, Any], field: str) -> list[str]:
    """Return a list of strings from an optional JSON field."""
    value = payload.get(field, [])
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"'{field}' must be a list of strings")
    return [item.strip() for item in value if item.strip()]


def parse_research_note(payload: object) -> SecurityResearchNote:
    """Validate JSON data and build a persisted security research note."""
    if not isinstance(payload, dict):
        raise ValueError("Input must be a JSON object")
    security_id = _required_text(payload, "security_id")
    symbol = _required_text(payload, "symbol")
    description = _required_text(payload, "description")
    summary = _required_text(payload, "summary")

    urgency_raw = payload.get("urgency_score")
    if urgency_raw is not None and (
        not isinstance(urgency_raw, int) or isinstance(urgency_raw, bool)
    ):
        raise ValueError("'urgency_score' must be an integer or null")
    position_value_raw = payload.get("position_value_eur")
    if position_value_raw is not None and (
        not isinstance(position_value_raw, (float, int))
        or isinstance(position_value_raw, bool)
    ):
        raise ValueError("'position_value_eur' must be a number or null")

    raw_sources = payload.get("sources", [])
    if not isinstance(raw_sources, list):
        raise ValueError("'sources' must be a list")
    sources: list[ResearchSource] = []
    for index, raw_source in enumerate(raw_sources):
        if not isinstance(raw_source, dict):
            raise ValueError(f"sources[{index}] must be an object")
        if not isinstance(raw_source.get("title"), str):
            raise ValueError(f"sources[{index}].title must be a string")
        if not isinstance(raw_source.get("publisher"), str):
            raise ValueError(f"sources[{index}].publisher must be a string")
        if not isinstance(raw_source.get("url"), str):
            raise ValueError(f"sources[{index}].url must be a string")
        published_at = raw_source.get("published_at")
        if published_at is not None and not isinstance(published_at, str):
            raise ValueError(f"sources[{index}].published_at must be text or null")
        full_text_read = raw_source.get("full_text_read", False)
        if not isinstance(full_text_read, bool):
            raise ValueError(f"sources[{index}].full_text_read must be a boolean")
        sources.append(
            ResearchSource(
                title=raw_source["title"].strip(),
                publisher=raw_source["publisher"].strip(),
                url=raw_source["url"].strip(),
                published_at=published_at,
                full_text_read=full_text_read,
            )
        )

    return SecurityResearchNote(
        security_id=security_id,
        symbol=symbol,
        description=description,
        summary=summary,
        findings=_text_list(payload, "findings"),
        limitations=_text_list(payload, "limitations"),
        sources=sources,
        urgency_score=urgency_raw,
        position_value_eur=(
            float(position_value_raw) if position_value_raw is not None else None
        ),
    )


def main(arguments: Sequence[str] | None = None) -> int:
    """Validate stdin JSON and append a note to the selected portfolio DB."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    options = parser.parse_args(arguments)
    try:
        payload = json.load(sys.stdin)
        note = parse_research_note(payload)
        researched_at = save_security_research_note(options.database, note)
    except (json.JSONDecodeError, ValueError, FileNotFoundError, sqlite3.Error, RuntimeError) as exc:
        parser.error(str(exc))
    print(
        f"Saved issuer research for {note.symbol} ({note.security_id}) "
        f"at {researched_at}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
