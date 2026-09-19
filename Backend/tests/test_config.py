import pytest

from sql_agent.config import BACKEND_DIR, ConfigError, load_settings


def test_defaults():
    s = load_settings({})
    assert s.model == "claude-opus-5"
    assert s.effort == "high"
    assert s.max_tokens == 16_000
    assert s.db_path == BACKEND_DIR / "synthea.db"
    assert s.as_of == "latest"
    assert s.refusal_fallback is True


def test_overrides_are_normalized():
    s = load_settings(
        {
            "SQL_AGENT_MODEL": "claude-sonnet-5",
            "SQL_AGENT_EFFORT": "XHIGH",
            "SQL_AGENT_MAX_TOKENS": "8000",
            "SQL_AGENT_AS_OF_DATE": "2025-12-31",
            "SQL_AGENT_REFUSAL_FALLBACK": "off",
        }
    )
    assert (s.model, s.effort, s.max_tokens, s.as_of, s.refusal_fallback) == (
        "claude-sonnet-5",
        "xhigh",
        8000,
        "2025-12-31",
        False,
    )


@pytest.mark.parametrize("value", ["latest", "today", " Today "])
def test_as_of_keywords(value):
    assert load_settings({"SQL_AGENT_AS_OF_DATE": value}).as_of == value.strip().lower()


def test_relative_db_path_resolves_against_backend_dir_not_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    s = load_settings({"SQL_AGENT_DB_PATH": "data/other.db"})
    assert s.db_path == BACKEND_DIR / "data" / "other.db"


def test_absolute_db_path_is_kept(tmp_path):
    db = tmp_path / "x.db"
    assert load_settings({"SQL_AGENT_DB_PATH": str(db)}).db_path == db


@pytest.mark.parametrize(
    "name,value",
    [
        ("SQL_AGENT_EFFORT", "extreme"),
        ("SQL_AGENT_MAX_TOKENS", "lots"),
        ("SQL_AGENT_MAX_TOKENS", "0"),
        ("SQL_AGENT_MAX_TOKENS", "200000"),
        ("SQL_AGENT_AS_OF_DATE", "last year"),
        ("SQL_AGENT_AS_OF_DATE", "2026-13-01"),
        ("SQL_AGENT_REFUSAL_FALLBACK", "maybe"),
    ],
)
def test_invalid_values_raise_with_variable_name(name, value):
    with pytest.raises(ConfigError, match=name):
        load_settings({name: value})


def test_settings_never_hold_the_api_key():
    s = load_settings({"ANTHROPIC_API_KEY": "sk-ant-test-not-a-real-key"})
    assert "sk-ant-test-not-a-real-key" not in repr(s)
