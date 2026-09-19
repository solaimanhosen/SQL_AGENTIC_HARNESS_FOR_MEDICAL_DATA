import sqlite3

import pytest

from sql_agent.config import load_settings
from sql_agent.db import (
    BlockedColumnError,
    QueryExecutionError,
    QueryTimeoutError,
    ReadOnlyDatabase,
)
from sql_agent.sql_guard import UnsafeQueryError

WRITE_ATTEMPTS = [
    "DROP TABLE patients",
    "DELETE FROM patients",
    "INSERT INTO patients (id) VALUES ('x')",
    "UPDATE patients SET city = 'x'",
    "CREATE TABLE evil (a TEXT)",
    "ATTACH DATABASE '/tmp/evil.db' AS evil",
    "PRAGMA writable_schema = ON",
    "SELECT 1; DROP TABLE patients",
]

BLOCKED_COLUMN_ATTEMPTS = [
    "SELECT ssn FROM patients",
    "SELECT * FROM patients",
    "SELECT p.last FROM patients p",
    "WITH leak AS (SELECT ssn FROM patients) SELECT * FROM leak",
    "SELECT (SELECT ssn FROM patients LIMIT 1) AS sneaky",
    "SELECT COUNT(*) FROM patients WHERE ssn LIKE '999%'",
    "SELECT address FROM patients ORDER BY ssn",
]


@pytest.fixture
def db(sample_db_path):
    return ReadOnlyDatabase(sample_db_path, max_rows=200, timeout_seconds=5)


def test_reads_work(db):
    result = db.run_query("SELECT encounterclass, COUNT(*) AS n FROM encounters GROUP BY 1 ORDER BY 1")
    assert result.columns == ("encounterclass", "n")
    assert result.rows == (("emergency", 2), ("wellness", 1))
    assert not result.truncated
    assert result.tables == ("encounters",)


@pytest.mark.parametrize("sql", WRITE_ATTEMPTS)
def test_writes_are_rejected_and_data_is_unchanged(db, sql):
    before = db.run_query("SELECT COUNT(*) FROM patients").rows
    with pytest.raises(UnsafeQueryError):
        db.run_query(sql)
    assert db.run_query("SELECT COUNT(*) FROM patients").rows == before


@pytest.mark.parametrize("sql", BLOCKED_COLUMN_ATTEMPTS)
def test_identity_columns_cannot_be_read(db, sql):
    with pytest.raises(BlockedColumnError, match="not available"):
        db.run_query(sql)


def test_allowed_patient_columns_still_work(db):
    result = db.run_query("SELECT gender, city, birthdate FROM patients ORDER BY id")
    assert result.rows == (("F", "Ames", "1980-01-01"), ("M", "Des Moines", "1990-05-05"))


def test_row_cap_marks_results_as_truncated(sample_db_path):
    db = ReadOnlyDatabase(sample_db_path, max_rows=2, timeout_seconds=5)
    result = db.run_query("SELECT id FROM encounters")
    assert result.row_count == 2
    assert result.truncated


def test_row_cap_does_not_override_a_smaller_limit(sample_db_path):
    db = ReadOnlyDatabase(sample_db_path, max_rows=2, timeout_seconds=5)
    result = db.run_query("SELECT id FROM encounters LIMIT 1")
    assert result.row_count == 1
    assert not result.truncated


def test_sql_mistakes_return_a_correctable_error(db):
    with pytest.raises(QueryExecutionError, match="no such column"):
        db.run_query("SELECT nope FROM patients")


def test_authorizer_blocks_writes_even_without_validation(db):
    """Layer 2 on its own: bypass the validator and go straight to the engine."""
    with db._connect(trusted=False) as conn:
        with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
            conn.execute("DELETE FROM patients")


def test_connection_is_read_only_even_without_the_authorizer(db):
    """Layer 1 on its own: a trusted connection still cannot write."""
    with db._connect(trusted=True) as conn:
        with pytest.raises(sqlite3.OperationalError, match="readonly database"):
            conn.execute("DELETE FROM patients")


def test_schema_introspection_hides_blocked_columns(db):
    visible = [column.name for column in db.table_columns("patients")]
    assert "ssn" not in visible and "gender" in visible
    everything = db.table_columns("patients", include_blocked=True)
    assert [column.name for column in everything if column.blocked] == [
        "ssn", "first", "last", "address",
    ]


def test_unknown_table_lists_the_known_ones(db):
    with pytest.raises(QueryExecutionError, match="Known tables"):
        db.table_columns("nope")


def test_missing_database_is_reported_clearly(tmp_path):
    db = ReadOnlyDatabase(tmp_path / "absent.db")
    with pytest.raises(QueryExecutionError, match="load_data"):
        db.run_query("SELECT 1")


def test_runaway_query_is_stopped():
    """A cartesian join over the real data would run for minutes; it must be cut off."""
    settings = load_settings({})
    if not settings.db_path.exists():
        pytest.skip("synthea.db not built; run python -m sql_agent.load_data")
    db = ReadOnlyDatabase(settings.db_path, max_rows=10, timeout_seconds=1)
    with pytest.raises(QueryTimeoutError, match="stopped after"):
        db.run_query("SELECT COUNT(*) FROM observations a, observations b, observations c")


def test_trailing_line_comment_does_not_break_the_row_cap(db):
    """The cap wraps the query, so a trailing comment must not swallow the closing bracket."""
    result = db.run_query("SELECT id FROM encounters ORDER BY id -- newest first")
    assert result.row_count == 3
