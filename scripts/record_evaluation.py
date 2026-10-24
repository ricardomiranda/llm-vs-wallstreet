"""Record the completion time of a successful portfolio evaluation."""

from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from import_portfolio import DEFAULT_DATABASE


def record_evaluation(database: Path) -> str:
    """Persist a UTC completion timestamp in a database with imported snapshots."""
    if not database.is_file():
        raise FileNotFoundError(f"Portfolio database not found: {database}")

    completed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with sqlite3.connect(database) as connection:
        snapshot_count = connection.execute(
            "SELECT COUNT(*) FROM snapshots"
        ).fetchone()
        if snapshot_count is None or snapshot_count[0] < 1:
            raise RuntimeError("No imported portfolio snapshots are available")
        connection.execute(
            """CREATE TABLE IF NOT EXISTS portfolio_evaluation_status (
                   singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
                   completed_at TEXT NOT NULL
               )"""
        )
        connection.execute(
            """INSERT INTO portfolio_evaluation_status(singleton_id, completed_at)
               VALUES (1, ?)
               ON CONFLICT(singleton_id) DO UPDATE SET
                   completed_at = excluded.completed_at""",
            (completed_at,),
        )
    return completed_at


def main(arguments: Sequence[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    options = parser.parse_args(arguments)
    try:
        completed_at = record_evaluation(options.database)
    except (FileNotFoundError, sqlite3.Error, RuntimeError) as exc:
        parser.error(str(exc))
    print(f"Portfolio evaluation completion recorded at {completed_at} UTC.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
