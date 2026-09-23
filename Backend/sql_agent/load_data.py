"""Build the SQLite database from the Synthea CSV files.

This module is the only component that writes to the database. Everything else opens it
read-only. The database is built in a temporary file and moved into place only after every
table loads and its row count matches the CSV, so a failed run never leaves a half-built
database behind.

Run it from the Backend folder, which is where the package is importable from:

    .venv/bin/python -m sql_agent.load_data
    .venv/bin/python -m sql_agent.load_data --csv-dir /path/to/csvs --db /path/to/out.db

The CSV and database paths themselves come from settings and do not depend on the
current directory, so the same command always reads and writes the same files.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine

from .config import ConfigError, load_settings

# Pandas reads any column containing blanks as floating point, which turns clinical codes
# into values like 44054006.0. Columns whose values are money, coordinates or averages keep
# that floating point type. Everything else that holds only whole numbers becomes an integer.
DECIMAL_NAME_PATTERN = re.compile(
    r"(cost|amount|payment|adjustment|transfer|outstanding|revenue|coverage"
    r"|expense|income|price|charge|avg|lat|lon)s?$"
)

# Single column indexes, created on every table that has the column.
INDEXED_COLUMNS = (
    "id", "patient", "encounter", "code", "start", "date", "claimid",
    "patientid", "providerid", "organization", "provider", "payer", "servicedate",
)

# Composite indexes for the joins the agent runs most often.
COMPOSITE_INDEXES = {
    "encounters": [("patient", "encounterclass"), ("patient", "start")],
    "conditions": [("patient", "code")],
    "observations": [("patient", "code")],
    "medications": [("patient", "code")],
    "procedures": [("patient", "code")],
}


class LoadError(RuntimeError):
    """Raised when the loaded data does not match the source CSV files."""


@dataclass(frozen=True)
class TableLoad:
    name: str
    rows: int
    columns: int
    csv_rows: int
    integer_columns: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return self.rows == self.csv_rows


def count_csv_rows(path: Path) -> int:
    """Count data rows with the csv module, independently of how pandas parsed the file."""
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        next(reader, None)  # header
        return sum(1 for _ in reader)


def normalize_frame(frame: pd.DataFrame) -> tuple[pd.DataFrame, tuple[str, ...]]:
    """Lower-case column names and store whole-number code columns as integers."""
    frame.columns = [str(c).strip().lower() for c in frame.columns]
    converted: list[str] = []
    for column in frame.columns:
        values = frame[column]
        if not pd.api.types.is_float_dtype(values) or DECIMAL_NAME_PATTERN.search(column):
            continue
        present = values.dropna()
        if present.empty or not (present % 1 == 0).all():
            continue
        frame[column] = values.astype("Int64")
        converted.append(column)
    return frame, tuple(converted)


def create_indexes(conn: sqlite3.Connection) -> int:
    """Create the indexes the agent's joins and filters rely on. Returns how many exist."""
    created = 0
    tables = [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    ]
    for table in tables:
        columns = {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')}
        wanted = [(column,) for column in INDEXED_COLUMNS if column in columns]
        wanted += [combo for combo in COMPOSITE_INDEXES.get(table, []) if set(combo) <= columns]
        for combo in wanted:
            name = f"idx_{table}_{'_'.join(combo)}"
            targets = ", ".join(f'"{column}"' for column in combo)
            conn.execute(f'CREATE INDEX IF NOT EXISTS "{name}" ON "{table}" ({targets})')
            created += 1
    conn.execute("ANALYZE")
    conn.commit()
    return created


def load_database(csv_dir: Path, db_path: Path, verbose: bool = True) -> list[TableLoad]:
    """Load every CSV in csv_dir into db_path. Raises LoadError if any row count disagrees."""
    csv_files = sorted(csv_dir.glob("*.csv"))
    if not csv_files:
        raise FileNotFoundError(f"No CSV files found in {csv_dir}")

    db_path.parent.mkdir(parents=True, exist_ok=True)
    staging_path = db_path.with_name(db_path.name + ".tmp")
    staging_path.unlink(missing_ok=True)

    try:
        engine = create_engine(f"sqlite:///{staging_path}")
        try:
            frames: dict[str, tuple[int, tuple[str, ...], Path]] = {}
            for path in csv_files:
                table = path.stem.strip().lower()
                frame, integer_columns = normalize_frame(pd.read_csv(path))
                frame.to_sql(table, engine, if_exists="replace", index=False)
                frames[table] = (len(frame.columns), integer_columns, path)
                if verbose:
                    print(f"  loaded {table:<22} {len(frame):>7,} rows")
        finally:
            engine.dispose()

        conn = sqlite3.connect(staging_path)
        try:
            index_count = create_indexes(conn)
            loads = [
                TableLoad(
                    name=table,
                    rows=conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0],
                    columns=column_count,
                    csv_rows=count_csv_rows(path),
                    integer_columns=integer_columns,
                )
                for table, (column_count, integer_columns, path) in frames.items()
            ]
        finally:
            conn.close()

        mismatched = [load for load in loads if not load.ok]
        if mismatched:
            detail = ", ".join(f"{m.name}: {m.rows} loaded vs {m.csv_rows} in CSV" for m in mismatched)
            raise LoadError(f"Row counts do not match the source files ({detail})")
    except BaseException:
        staging_path.unlink(missing_ok=True)
        raise

    os.replace(staging_path, db_path)
    if verbose:
        print(f"  created {index_count} indexes")
    return loads


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--csv-dir", type=Path, help="folder of Synthea CSV files")
    parser.add_argument("--db", type=Path, help="database file to write")
    parser.add_argument("--quiet", action="store_true", help="only print the summary")
    args = parser.parse_args(argv)

    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"Settings error: {exc}", file=sys.stderr)
        return 1

    csv_dir = args.csv_dir or settings.csv_dir
    db_path = args.db or settings.db_path

    print(f"Loading {csv_dir} into {db_path}")
    started = time.monotonic()
    try:
        loads = load_database(csv_dir, db_path, verbose=not args.quiet)
    except (FileNotFoundError, LoadError) as exc:
        print(f"Load failed: {exc}", file=sys.stderr)
        return 1

    total_rows = sum(load.rows for load in loads)
    integer_columns = sum(len(load.integer_columns) for load in loads)
    size_mb = db_path.stat().st_size / 1_000_000
    print(
        f"\nLoaded {len(loads)} tables, {total_rows:,} rows in {time.monotonic() - started:.1f}s. "
        f"Row counts match the CSV files.\n"
        f"{integer_columns} code columns stored as integers. Database size {size_mb:.0f} MB."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
