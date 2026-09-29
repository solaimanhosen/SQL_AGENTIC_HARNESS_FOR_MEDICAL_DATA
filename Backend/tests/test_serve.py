import pytest

from sql_agent import serve


@pytest.fixture
def launched(monkeypatch, sample_db_path):
    calls = []
    monkeypatch.setenv("SQL_AGENT_DB_PATH", str(sample_db_path))
    monkeypatch.setattr(serve, "create_app", lambda **kwargs: calls.append(kwargs) or "app")
    monkeypatch.setattr(serve.uvicorn, "run", lambda app, **kwargs: calls.append(kwargs))
    return calls


def test_an_open_service_refuses_to_listen_beyond_this_machine(launched, monkeypatch, capsys):
    monkeypatch.setenv("SQL_AGENT_API_TOKEN", "")
    assert serve.main(["--host", "0.0.0.0"]) == 1
    assert "without SQL_AGENT_API_TOKEN" in capsys.readouterr().err
    assert launched == []


def test_with_a_token_it_may_listen_anywhere_and_requires_it(launched, monkeypatch):
    monkeypatch.setenv("SQL_AGENT_API_TOKEN", "t" * 40)
    assert serve.main(["--host", "0.0.0.0", "--port", "9000"]) == 0
    assert launched == [{"api_token": "t" * 40}, {"host": "0.0.0.0", "port": 9000}]


def test_locally_it_runs_without_a_token(launched, monkeypatch):
    monkeypatch.setenv("SQL_AGENT_API_TOKEN", "")
    assert serve.main([]) == 0
    assert launched[0] == {"api_token": None}


def test_a_short_token_is_a_settings_error(launched, monkeypatch, capsys):
    monkeypatch.setenv("SQL_AGENT_API_TOKEN", "short")
    assert serve.main([]) == 1
    assert "at least 32 characters" in capsys.readouterr().err
