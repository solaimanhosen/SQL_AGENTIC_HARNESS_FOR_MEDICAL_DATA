import sqlite3

import pytest

from sql_agent import passwords


# Secrets from Backend/.env that would reach a real service. They are set empty, not removed,
# because loading .env never replaces a variable that is already set.
REAL_SERVICE_SETTINGS = (
    "SQL_AGENT_GOOGLE_CLIENT_ID",
    "SQL_AGENT_GOOGLE_CLIENT_SECRET",
    "SQL_AGENT_SMTP_HOST",
    "SQL_AGENT_SMTP_USERNAME",
    "SQL_AGENT_SMTP_PASSWORD",
    "SQL_AGENT_MAIL_FROM",
)


@pytest.fixture(autouse=True)
def no_real_google_or_mail(monkeypatch):
    """No test signs in to Google or sends an email, whatever Backend/.env holds."""
    for name in REAL_SERVICE_SETTINGS:
        monkeypatch.setenv(name, "")


@pytest.fixture(autouse=True)
def quick_password_hashing(monkeypatch):
    """Real scrypt, at a cost small enough that tests that sign in stay fast."""
    monkeypatch.setattr(passwords, "COST", (2**10, 8, 1))


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
