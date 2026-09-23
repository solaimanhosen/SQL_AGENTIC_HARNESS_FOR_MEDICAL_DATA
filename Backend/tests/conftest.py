import sqlite3

import pytest


@pytest.fixture(scope="session")
def sample_db_path(tmp_path_factory):
    """A small stand-in for synthea.db, with the identity columns the agent must not read."""
    path = tmp_path_factory.mktemp("db") / "sample.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE patients (
            id TEXT, ssn TEXT, first TEXT, last TEXT, address TEXT,
            birthdate TEXT, gender TEXT, city TEXT
        );
        INSERT INTO patients VALUES
            ('p1', '999-11-1111', 'Ann', 'Lee', '1 Oak St', '1980-01-01', 'F', 'Ames'),
            ('p2', '999-22-2222', 'Bo', 'Ray', '2 Elm St', '1990-05-05', 'M', 'Des Moines');

        CREATE TABLE encounters (id TEXT, patient TEXT, encounterclass TEXT, start TEXT);
        INSERT INTO encounters VALUES
            ('e1', 'p1', 'emergency', '2026-01-01T10:00:00Z'),
            ('e2', 'p2', 'wellness',  '2026-02-01T10:00:00Z'),
            ('e3', 'p1', 'emergency', '2026-03-01T10:00:00Z');
        """
    )
    conn.commit()
    conn.close()
    return path
