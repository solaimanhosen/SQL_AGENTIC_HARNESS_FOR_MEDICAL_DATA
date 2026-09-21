import pytest

from sql_agent import check_setup
from sql_agent.config import load_settings

FAKE_KEY = "sk-ant-test-not-a-real-key"


def test_api_key_value_is_never_printed(monkeypatch, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEY)
    assert check_setup.check_api_key() is True
    assert FAKE_KEY not in capsys.readouterr().out


def test_missing_api_key_fails(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert check_setup.check_api_key() is False


def test_missing_database_fails(tmp_path):
    settings = load_settings({"SQL_AGENT_DB_PATH": str(tmp_path / "missing.db")})
    assert check_setup.check_database(settings) is False
    assert not (tmp_path / "missing.db").exists(), "read-only open must not create the file"


def test_real_database_opens_read_only():
    settings = load_settings({})
    if not settings.db_path.exists():
        pytest.skip("synthea.db not built; run load_csv_to_sqlite.py")
    assert check_setup.check_database(settings) is True


def test_table_count_ignores_sqlite_internal_tables(capsys):
    """ANALYZE writes sqlite_stat1, which should not be counted as one of the data tables."""
    settings = load_settings({})
    if not settings.db_path.exists():
        pytest.skip("synthea.db not built; run python -m sql_agent.load_data")
    assert check_setup.check_database(settings) is True
    assert "18 tables" in capsys.readouterr().out
