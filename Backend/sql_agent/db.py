"""Read-only access to the Synthea database.

Three independent layers stand between model-written SQL and the data:

1. The file is opened read-only, so this process cannot write to it at all.
2. A SQLite authorizer runs inside the engine and rejects every action except reading
   permitted tables and columns, so a write would fail even if it slipped past validation.
3. `sql_guard.validate_query` rejects anything that is not a single SELECT.

Direct identity columns such as names and social security numbers are blocked at layer 2.
This data is synthetic, but the agent should never have a path to columns like these.
Coarse geography such as city, state, county and postal code stays available, because
analysts group by it and it does not identify a person on its own.
"""

from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .config import Settings
from .sql_guard import UnsafeQueryError, validate_query

DEFAULT_MAX_ROWS = 200
DEFAULT_TIMEOUT_SECONDS = 15.0

# Columns the agent may never read, by table.
BLOCKED_COLUMNS: dict[str, frozenset[str]] = {
    "patients": frozenset(
        {
            "ssn", "drivers", "passport", "prefix", "first", "middle",
            "last", "suffix", "maiden", "address", "lat", "lon", "birthplace",
        }
    ),
}

# Actions the authorizer permits. Reads are permitted per column, see _authorize.
_ALLOWED_ACTIONS = frozenset({sqlite3.SQLITE_SELECT, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE})

# How often SQLite checks whether the query has run out of time, in virtual machine steps.
_PROGRESS_STEPS = 2_000

# Engine limits for untrusted queries. Without the length limit a single expression such as
# randomblob(200000000) allocates hundreds of megabytes before any row is returned.
_ENGINE_LIMITS = {
    "SQLITE_LIMIT_LENGTH": 1_000_000,  # bytes in one string or blob
    "SQLITE_LIMIT_SQL_LENGTH": 100_000,  # characters in one statement
    "SQLITE_LIMIT_EXPR_DEPTH": 200,
    "SQLITE_LIMIT_COMPOUND_SELECT": 50,
    "SQLITE_LIMIT_LIKE_PATTERN_LENGTH": 1_000,
    "SQLITE_LIMIT_ATTACHED": 0,  # no attached databases, on top of the authorizer
}


def _apply_engine_limits(conn: sqlite3.Connection) -> None:
    """Cap what one statement may allocate, nest or attach."""
    for name, value in _ENGINE_LIMITS.items():
        identifier = getattr(sqlite3, name, None)
        if identifier is not None:
            conn.setlimit(identifier, value)


class QueryExecutionError(RuntimeError):
    """The database could not run the query, for example an unknown column or a syntax error."""


class QueryTimeoutError(RuntimeError):
    """The query was stopped because it exceeded the time limit."""


class BlockedColumnError(UnsafeQueryError):
    """The query asked for a column the agent is not allowed to read."""


@dataclass(frozen=True)
class ColumnInfo:
    name: str
    type: str
    blocked: bool


@dataclass(frozen=True)
class QueryResult:
    sql: str
    columns: tuple[str, ...]
    rows: tuple[tuple, ...]
    truncated: bool
    """True when the query produced more rows than the row limit, so rows are incomplete."""
    elapsed_ms: float
    tables: tuple[str, ...]

    @property
    def row_count(self) -> int:
        return len(self.rows)


class ReadOnlyDatabase:
    """Runs validated SELECT statements against the database and nothing else."""

    def __init__(
        self,
        db_path: Path | str,
        *,
        max_rows: int = DEFAULT_MAX_ROWS,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        blocked_columns: dict[str, frozenset[str]] | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.max_rows = max_rows
        self.timeout_seconds = timeout_seconds
        self.blocked_columns = BLOCKED_COLUMNS if blocked_columns is None else blocked_columns

    @classmethod
    def from_settings(cls, settings: Settings) -> "ReadOnlyDatabase":
        return cls(
            settings.db_path,
            max_rows=settings.max_rows,
            timeout_seconds=settings.query_timeout_seconds,
        )

    def blocked_columns_for(self, table: str) -> frozenset[str]:
        return self.blocked_columns.get(table.lower(), frozenset())

    def run_query(self, sql: str) -> QueryResult:
        """Validate and run a single SELECT, returning at most `max_rows` rows.

        Raises UnsafeQueryError if the statement is not a read, BlockedColumnError if it
        reads a blocked column, QueryTimeoutError on the time limit, and
        QueryExecutionError for ordinary SQL mistakes the caller can correct.
        """
        validated = validate_query(sql)
        # The cap is applied by wrapping rather than by editing the statement, so a query
        # that already has its own LIMIT keeps it. One extra row reveals truncation.
        capped = f"SELECT * FROM (\n{validated.sql}\n) LIMIT {self.max_rows + 1}"

        started = time.perf_counter()
        with self._connect(trusted=False, deadline=time.monotonic() + self.timeout_seconds) as conn:
            try:
                cursor = conn.execute(capped)
                rows = cursor.fetchall()
                columns = tuple(description[0] for description in cursor.description or ())
            except sqlite3.OperationalError as exc:
                if "interrupted" in str(exc).lower():
                    raise QueryTimeoutError(
                        f"The query was stopped after {self.timeout_seconds:.0f} seconds. "
                        "Add filters, aggregate in SQL, or query fewer tables at once."
                    ) from None
                raise QueryExecutionError(str(exc)) from None
            except sqlite3.DatabaseError as exc:
                raise self._translate_denial(str(exc)) from None

        elapsed_ms = (time.perf_counter() - started) * 1000
        return QueryResult(
            sql=validated.sql,
            columns=columns,
            rows=tuple(rows[: self.max_rows]),
            truncated=len(rows) > self.max_rows,
            elapsed_ms=elapsed_ms,
            tables=validated.tables,
        )

    def table_names(self) -> tuple[str, ...]:
        with self._connect(trusted=True) as conn:
            return tuple(
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
                )
            )

    def table_columns(self, table: str, *, include_blocked: bool = False) -> tuple[ColumnInfo, ...]:
        """Describe one table. Blocked columns are hidden unless explicitly requested."""
        known = {name.lower(): name for name in self.table_names()}
        actual = known.get(table.lower())
        if actual is None:
            raise QueryExecutionError(f"Unknown table {table!r}. Known tables: {', '.join(known.values())}.")
        blocked = self.blocked_columns_for(actual)
        with self._connect(trusted=True) as conn:
            rows = conn.execute(f'PRAGMA table_info("{actual}")').fetchall()
        columns = tuple(ColumnInfo(name=row[1], type=row[2], blocked=row[1].lower() in blocked) for row in rows)
        return columns if include_blocked else tuple(column for column in columns if not column.blocked)

    @contextmanager
    def _connect(self, *, trusted: bool, deadline: float | None = None) -> Iterator[sqlite3.Connection]:
        """Open the database read-only.

        Trusted connections run this module's own fixed SQL, such as schema introspection,
        and skip the authorizer so that PRAGMA statements work. Everything that originates
        from the model goes through an untrusted connection.
        """
        if not self.db_path.exists():
            raise QueryExecutionError(
                f"Database not found at {self.db_path}. Build it with python -m sql_agent.load_data."
            )
        conn = sqlite3.connect(f"{self.db_path.as_uri()}?mode=ro", uri=True)
        try:
            # Set before the authorizer, which denies PRAGMA statements.
            conn.execute("PRAGMA query_only = ON")
            if deadline is not None:
                conn.set_progress_handler(lambda: int(time.monotonic() > deadline), _PROGRESS_STEPS)
            if not trusted:
                _apply_engine_limits(conn)
                conn.set_authorizer(self._authorize)
            yield conn
        finally:
            conn.close()

    def _authorize(self, action: int, arg1: str | None, arg2: str | None, db_name: str | None, trigger: str | None) -> int:
        if action == sqlite3.SQLITE_READ:
            table = (arg1 or "").lower()
            column = (arg2 or "").lower()
            # Internal tables hold the schema, which the agent gets from the catalog instead.
            if table.startswith("sqlite_"):
                return sqlite3.SQLITE_DENY
            if column and column in self.blocked_columns_for(table):
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        if action in _ALLOWED_ACTIONS:
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY

    def _translate_denial(self, message: str) -> Exception:
        if "prohibited" in message and "sqlite_" in message:
            return UnsafeQueryError(
                "The internal schema tables are not readable. Use describe_table to see what a "
                "table holds."
            )
        if "prohibited" in message:
            return BlockedColumnError(
                f"{message.capitalize()}. Identity columns such as names, addresses and "
                "identifiers are not available to this agent. Select the columns you need "
                "instead of using SELECT *."
            )
        return UnsafeQueryError(
            f"The database refused this statement: {message}. Only read-only SELECT statements are allowed."
        )
