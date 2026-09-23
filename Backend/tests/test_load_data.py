import sqlite3

import pytest

from sql_agent import load_data
from sql_agent.config import load_settings
from sql_agent.load_data import LoadError, load_database


@pytest.fixture
def csv_dir(tmp_path):
    folder = tmp_path / "csvs"
    folder.mkdir()
    (folder / "patients.csv").write_text(
        "Id,BIRTHDATE,FIPS,HEALTHCARE_EXPENSES\n"
        "p1,1980-01-01,19153,1234.56\n"
        "p2,1990-05-05,,20.00\n"
    )
    (folder / "encounters.csv").write_text(
        "Id,PATIENT,CODE,START,ENCOUNTERCLASS,REASONCODE,BASE_ENCOUNTER_COST\n"
        "e1,p1,162673000,2026-01-01T10:00:00Z,emergency,44054006,136.00\n"
        "e2,p2,162673000,2026-02-01T10:00:00Z,wellness,,136.00\n"
    )
    return folder


def _connect(db_path):
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def test_tables_rows_and_lower_case_columns(csv_dir, tmp_path):
    db_path = tmp_path / "out.db"
    loads = load_database(csv_dir, db_path, verbose=False)

    assert {load.name for load in loads} == {"patients", "encounters"}
    assert all(load.ok for load in loads)
    conn = _connect(db_path)
    columns = [row[1] for row in conn.execute('PRAGMA table_info("encounters")')]
    assert columns == ["id", "patient", "code", "start", "encounterclass", "reasoncode", "base_encounter_cost"]
    assert conn.execute("SELECT COUNT(*) FROM patients").fetchone()[0] == 2


def test_codes_become_integers_but_money_stays_decimal(csv_dir, tmp_path):
    db_path = tmp_path / "out.db"
    load_database(csv_dir, db_path, verbose=False)
    conn = _connect(db_path)

    # reasoncode and fips have blanks, so pandas reads them as floats; the loader fixes that.
    assert conn.execute("SELECT typeof(reasoncode) FROM encounters WHERE id = 'e1'").fetchone()[0] == "integer"
    assert conn.execute("SELECT reasoncode FROM encounters WHERE id = 'e1'").fetchone()[0] == 44054006
    assert conn.execute("SELECT typeof(fips) FROM patients WHERE id = 'p1'").fetchone()[0] == "integer"
    assert conn.execute("SELECT fips FROM patients WHERE id = 'p2'").fetchone()[0] is None
    # Whole-number money must not be turned into an integer column.
    assert conn.execute("SELECT typeof(base_encounter_cost) FROM encounters WHERE id = 'e1'").fetchone()[0] == "real"


def test_indexes_are_created(csv_dir, tmp_path):
    db_path = tmp_path / "out.db"
    load_database(csv_dir, db_path, verbose=False)
    conn = _connect(db_path)
    indexes = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
    assert {"idx_encounters_patient", "idx_encounters_code", "idx_encounters_patient_encounterclass"} <= indexes


def test_unreadable_csv_leaves_the_existing_database_untouched(csv_dir, tmp_path):
    db_path = tmp_path / "out.db"
    load_database(csv_dir, db_path, verbose=False)
    (csv_dir / "broken.csv").write_bytes(b"a,b\n\xff\xfe,2\n")

    with pytest.raises(UnicodeDecodeError):
        load_database(csv_dir, db_path, verbose=False)

    conn = _connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM patients").fetchone()[0] == 2
    assert not db_path.with_name(db_path.name + ".tmp").exists()


def test_row_count_mismatch_raises_and_keeps_the_old_database(csv_dir, tmp_path, monkeypatch):
    db_path = tmp_path / "out.db"
    load_database(csv_dir, db_path, verbose=False)
    monkeypatch.setattr(load_data, "count_csv_rows", lambda path: 99)

    with pytest.raises(LoadError, match="Row counts do not match"):
        load_database(csv_dir, db_path, verbose=False)

    conn = _connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM patients").fetchone()[0] == 2
    assert not db_path.with_name(db_path.name + ".tmp").exists()


def test_empty_csv_folder_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_database(tmp_path, tmp_path / "out.db", verbose=False)


def test_real_database_uses_an_index_for_a_patient_lookup():
    """The tiny fixtures above are too small for the planner to prefer an index; the real data is not."""
    settings = load_settings({})
    if not settings.db_path.exists():
        pytest.skip("synthea.db not built; run python -m sql_agent.load_data")
    conn = _connect(settings.db_path)
    plan = conn.execute(
        "EXPLAIN QUERY PLAN SELECT id FROM encounters WHERE patient = 'x' AND encounterclass = 'emergency'"
    ).fetchall()
    assert any("idx_encounters_patient" in str(step) for step in plan), plan
