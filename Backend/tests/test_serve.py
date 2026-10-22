import pytest

from sql_agent import serve


@pytest.fixture
def launched(monkeypatch, sample_db_path):
    calls = []
    monkeypatch.setenv("SQL_AGENT_DB_PATH", str(sample_db_path))
    monkeypatch.setattr(serve, "create_app", lambda **kwargs: calls.append(kwargs) or "app")
    monkeypatch.setattr(serve.uvicorn, "run", lambda app, **kwargs: calls.append(kwargs))
    return calls


def test_plain_http_cookies_are_refused_beyond_this_machine(launched, monkeypatch, capsys):
    monkeypatch.setenv("SQL_AGENT_SECURE_COOKIES", "false")
    assert serve.main(["--host", "0.0.0.0"]) == 1
    assert "SQL_AGENT_SECURE_COOKIES=false" in capsys.readouterr().err
    assert launched == []


def test_with_secure_cookies_it_may_listen_anywhere(launched, monkeypatch):
    monkeypatch.setenv("SQL_AGENT_SECURE_COOKIES", "true")
    assert serve.main(["--host", "0.0.0.0", "--port", "9000"]) == 0
    assert launched == [{}, {"host": "0.0.0.0", "port": 9000}]


def test_locally_it_runs_with_plain_http_cookies(launched, monkeypatch, capsys):
    monkeypatch.setenv("SQL_AGENT_SECURE_COOKIES", "false")
    monkeypatch.delenv("SQL_AGENT_GOOGLE_CLIENT_ID", raising=False)
    assert serve.main([]) == 0
    assert "Google sign-in off" in capsys.readouterr().err
