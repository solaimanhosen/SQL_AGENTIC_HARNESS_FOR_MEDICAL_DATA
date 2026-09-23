"""Run one SQL statement through the agent's guardrails and print the result.

This is a hand tool for checking the safety layer and exploring the data. It uses exactly
the path the agent will use, so anything rejected here is rejected for the agent too.

Run from the Backend folder:
    .venv/bin/python -m sql_agent.run_sql "SELECT encounterclass, COUNT(*) FROM encounters GROUP BY 1"
    .venv/bin/python -m sql_agent.run_sql "DROP TABLE patients"
"""

from __future__ import annotations

import argparse
import sys

from .config import ConfigError, load_settings
from .db import ReadOnlyDatabase
from .formatting import format_table


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one read-only SQL statement through the guardrails.")
    parser.add_argument("sql", help="the SQL statement to run")
    args = parser.parse_args(argv)

    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"Settings error: {exc}", file=sys.stderr)
        return 1

    db = ReadOnlyDatabase.from_settings(settings)
    try:
        result = db.run_query(args.sql)
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(format_table(result.columns, result.rows))
    summary = f"\n{result.row_count} rows in {result.elapsed_ms:.1f} ms from {', '.join(result.tables) or 'no tables'}"
    if result.truncated:
        summary += f" (capped at {db.max_rows} rows; more rows matched)"
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
