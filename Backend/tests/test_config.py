import pytest

from sql_agent.config import BACKEND_DIR, ConfigError, load_settings


def test_defaults():
    s = load_settings({})
    assert s.model == "claude-opus-5"
    assert s.effort == "high"
    assert s.max_tokens == 16_000
    assert s.db_path == BACKEND_DIR / "synthea.db"
    assert s.csv_dir == BACKEND_DIR / "data" / "synthea"
    assert s.as_of == "latest"
    assert s.max_rows == 200
    assert s.log_path == BACKEND_DIR / "logs" / "runs.jsonl"
    assert s.query_timeout_seconds == 15.0
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


def test_logging_can_be_switched_off_or_moved(tmp_path):
    assert load_settings({"SQL_AGENT_LOG_PATH": "off"}).log_path is None
    assert load_settings({"SQL_AGENT_LOG_PATH": ""}).log_path is None
    assert load_settings({"SQL_AGENT_LOG_PATH": str(tmp_path / "r.jsonl")}).log_path == tmp_path / "r.jsonl"


def test_query_limits_can_be_tuned():
    s = load_settings({"SQL_AGENT_MAX_ROWS": "50", "SQL_AGENT_QUERY_TIMEOUT": "2.5"})
    assert (s.max_rows, s.query_timeout_seconds) == (50, 2.5)


def test_cors_origins_default_to_the_angular_dev_server_and_can_be_listed():
    assert load_settings({}).cors_origins == ("http://localhost:4200",)
    s = load_settings({"SQL_AGENT_CORS_ORIGINS": " http://localhost:4200/, https://demo.example.org "})
    assert s.cors_origins == ("http://localhost:4200", "https://demo.example.org")


def test_analysis_row_cap_defaults_and_bounds():
    assert load_settings({}).analysis_max_rows == 100_000
    assert load_settings({"SQL_AGENT_ANALYSIS_MAX_ROWS": "5000"}).analysis_max_rows == 5000
    for bad in ("0", "2000000", "lots"):
        with pytest.raises(ConfigError, match="SQL_AGENT_ANALYSIS_MAX_ROWS"):
            load_settings({"SQL_AGENT_ANALYSIS_MAX_ROWS": bad})


def test_csv_dir_override(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert load_settings({"SQL_AGENT_CSV_DIR": "data/other"}).csv_dir == BACKEND_DIR / "data" / "other"


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
        ("SQL_AGENT_MAX_ROWS", "0"),
        ("SQL_AGENT_MAX_ROWS", "20000"),
        ("SQL_AGENT_MAX_ROWS", "many"),
        ("SQL_AGENT_QUERY_TIMEOUT", "0"),
        ("SQL_AGENT_QUERY_TIMEOUT", "600"),
        ("SQL_AGENT_QUERY_TIMEOUT", "soon"),
        ("SQL_AGENT_REFUSAL_FALLBACK", "maybe"),
        ("SQL_AGENT_CORS_ORIGINS", "*"),
        ("SQL_AGENT_MAX_CONCURRENT_RUNS", "0"),
        ("SQL_AGENT_DAILY_TOKEN_BUDGET", "1000"),
        ("SQL_AGENT_CONVERSATION_TOKEN_BUDGET", "lots"),
        ("SQL_AGENT_CORS_ORIGINS", "localhost:4200"),
        ("SQL_AGENT_CORS_ORIGINS", "http://localhost:4200/app"),
    ],
)
def test_invalid_values_raise_with_variable_name(name, value):
    with pytest.raises(ConfigError, match=name):
        load_settings({name: value})


def test_settings_never_hold_the_api_key():
    s = load_settings({"ANTHROPIC_API_KEY": "sk-ant-test-not-a-real-key"})
    assert "sk-ant-test-not-a-real-key" not in repr(s)


def test_service_limits_have_defaults_and_can_be_tuned():
    s = load_settings({})
    assert (s.max_concurrent_runs, s.daily_token_budget, s.conversation_token_budget) == (4, 5_000_000, 1_000_000)
    assert s.request_log_path == BACKEND_DIR / "logs" / "requests.jsonl"
    s = load_settings({"SQL_AGENT_MAX_CONCURRENT_RUNS": "2", "SQL_AGENT_REQUEST_LOG_PATH": "off"})
    assert s.max_concurrent_runs == 2 and s.request_log_path is None


def test_account_settings_have_safe_defaults_and_are_checked():
    s = load_settings({})
    assert s.secure_cookies is True and s.registration_open is True
    assert s.public_url == "http://localhost:4200" and s.user_daily_token_budget == 1_000_000
    custom = load_settings({"SQL_AGENT_PUBLIC_URL": "https://agent.example.org/", "SQL_AGENT_REGISTRATION": "closed"})
    assert custom.public_url == "https://agent.example.org" and custom.registration_open is False
    for name, value in (("SQL_AGENT_PUBLIC_URL", "agent.example.org"), ("SQL_AGENT_REGISTRATION", "maybe")):
        with pytest.raises(ConfigError, match=name):
            load_settings({name: value})

def test_conversations_are_stored_by_default_and_can_be_kept_in_memory():
    s = load_settings({})
    assert s.conversations_path == BACKEND_DIR / "data" / "conversations.db" and s.store_result_rows is True
    s = load_settings({"SQL_AGENT_CONVERSATIONS_PATH": "off", "SQL_AGENT_STORE_RESULT_ROWS": "false"})
    assert s.conversations_path is None and s.store_result_rows is False


def test_the_default_model_must_be_one_the_picker_offers():
    assert load_settings({"SQL_AGENT_MODEL": "claude-sonnet-5-5"}).model == "claude-sonnet-5-5"
    with pytest.raises(ConfigError, match="SQL_AGENT_MODEL"):
        load_settings({"SQL_AGENT_MODEL": "claude-2"})
