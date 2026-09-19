import pytest

from sql_agent.sql_guard import UnsafeQueryError, validate_query

WRITE_ATTEMPTS = [
    "DROP TABLE patients",
    "DELETE FROM patients",
    "INSERT INTO patients (id) VALUES ('x')",
    "UPDATE patients SET city = 'x'",
    "CREATE TABLE evil (a TEXT)",
    "ALTER TABLE patients ADD COLUMN evil TEXT",
    "CREATE VIEW evil AS SELECT * FROM patients",
    "VACUUM",
    "REINDEX",
    "ATTACH DATABASE '/tmp/evil.db' AS evil",
    "DETACH DATABASE main",
    "PRAGMA writable_schema = ON",
]

MULTI_STATEMENT_ATTEMPTS = [
    "SELECT 1; DROP TABLE patients",
    "SELECT 1 -- hide\n; DELETE FROM patients",
    "SELECT 1;\nUPDATE patients SET city = 'x';",
    "BEGIN; SELECT 1",
]

VALID_QUERIES = [
    "SELECT COUNT(*) FROM patients",
    "SELECT COUNT(*) FROM patients;",
    "  SELECT 1  ",
    "WITH recent AS (SELECT patient FROM encounters WHERE encounterclass = 'emergency')"
    " SELECT COUNT(DISTINCT patient) FROM recent",
    "SELECT gender FROM patients UNION SELECT gender FROM patients",
    "SELECT p.gender, COUNT(e.id) FROM patients p JOIN encounters e ON e.patient = p.id GROUP BY 1",
    "SELECT COUNT(*) FROM encounters WHERE date(start) > date('2026-08-16', '-12 months')",
    "SELECT patient, ROW_NUMBER() OVER (PARTITION BY patient ORDER BY start) AS n FROM encounters",
]


@pytest.mark.parametrize("sql", WRITE_ATTEMPTS)
def test_write_and_admin_statements_are_rejected(sql):
    with pytest.raises(UnsafeQueryError, match="read-only SELECT"):
        validate_query(sql)


@pytest.mark.parametrize("sql", MULTI_STATEMENT_ATTEMPTS)
def test_multiple_statements_are_rejected(sql):
    with pytest.raises(UnsafeQueryError, match="one statement at a time"):
        validate_query(sql)


@pytest.mark.parametrize("sql", VALID_QUERIES)
def test_analytic_queries_are_allowed(sql):
    assert validate_query(sql).sql


def test_empty_query_is_rejected():
    with pytest.raises(UnsafeQueryError, match="empty"):
        validate_query("   ")


def test_unparseable_query_is_rejected():
    with pytest.raises(UnsafeQueryError, match="not valid SQLite"):
        validate_query("SELECT FROM WHERE )(")


def test_trailing_semicolon_is_stripped_and_tables_are_reported():
    validated = validate_query("SELECT * FROM encounters JOIN patients ON 1 = 1;")
    assert not validated.sql.endswith(";")
    assert validated.tables == ("encounters", "patients")
