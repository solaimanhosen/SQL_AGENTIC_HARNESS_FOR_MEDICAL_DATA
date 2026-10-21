"""Runtime settings, loaded from environment variables and the git-ignored Backend/.env file.

The Anthropic API key is deliberately not part of Settings. The Anthropic SDK and
LangChain read ANTHROPIC_API_KEY straight from the environment, and keeping it out
of this object means printing or logging Settings can never leak it.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

from .models import CATALOG, VALID_EFFORTS, find_model

BACKEND_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BACKEND_DIR / ".env"

DEFAULT_MODEL = "claude-opus-5"
DEFAULT_EFFORT = "high"
DEFAULT_MAX_TOKENS = 16_000
DEFAULT_DB_PATH = "synthea.db"
DEFAULT_CSV_DIR = "data/synthea"
DEFAULT_AS_OF = "latest"
DEFAULT_MAX_ROWS = 200
DEFAULT_ANALYSIS_MAX_ROWS = 100_000
DEFAULT_QUERY_TIMEOUT = 15.0
DEFAULT_LOG_PATH = "logs/runs.jsonl"
DEFAULT_CORS_ORIGINS = "http://localhost:4200"
DEFAULT_REQUEST_LOG_PATH = "logs/requests.jsonl"
DEFAULT_MAX_CONCURRENT_RUNS = 4
DEFAULT_DAILY_TOKEN_BUDGET = 5_000_000
DEFAULT_CONVERSATION_TOKEN_BUDGET = 1_000_000
DEFAULT_CONVERSATIONS_PATH = "data/conversations.db"
DEFAULT_USER_DAILY_TOKEN_BUDGET = 1_000_000
DEFAULT_PUBLIC_URL = "http://localhost:4200"

MAX_OUTPUT_TOKENS = 128_000
AS_OF_KEYWORDS = ("latest", "today")


class ConfigError(ValueError):
    """Raised when a setting has an invalid value."""


@dataclass(frozen=True)
class Settings:
    model: str
    effort: str
    max_tokens: int
    db_path: Path
    csv_dir: Path
    """Folder holding the Synthea CSV files that the loader reads."""
    as_of: str
    """Anchor for relative time windows such as "last 12 months" (see Documents/decisions/0002).

    "latest" means the last encounter date in the data, "today" means the real
    current date, and a YYYY-MM-DD value pins an explicit date.
    """
    max_rows: int
    """Largest number of rows a single agent query may return."""
    query_timeout_seconds: float
    """Time limit for a single agent query, after which it is stopped."""
    log_path: Path | None
    """Where each run is appended as JSON, or None when logging is switched off."""
    refusal_fallback: bool
    cors_origins: tuple[str, ...]
    """Browser origins allowed to call the HTTP service, such as the Angular dev server."""
    request_log_path: Path | None
    """Where the service appends one line per HTTP request, or None when switched off."""
    max_concurrent_runs: int
    """Questions the service will answer at once. More are refused rather than queued."""
    daily_token_budget: int
    """Model tokens, input and output together, the service may spend per UTC day."""
    conversation_token_budget: int
    """Model tokens one conversation may spend, so a long conversation cannot run away."""
    conversations_path: Path | None = None
    """The database the service keeps conversations in, or None to keep them in memory."""
    store_result_rows: bool = True
    """Whether a stored answer keeps the rows its queries returned, or only what ran."""
    analysis_max_rows: int = DEFAULT_ANALYSIS_MAX_ROWS
    """Rows an analytics tool may read. Only its computed table reaches the model."""
    user_daily_token_budget: int = DEFAULT_USER_DAILY_TOKEN_BUDGET
    """Model tokens one person may spend per UTC day, beside the service's own budget."""
    secure_cookies: bool = True
    """Whether the session cookie is sent only over HTTPS. Off only for plain-HTTP local use."""
    public_url: str = DEFAULT_PUBLIC_URL
    """The address people open the application at. Google returns them to it after sign-in."""
    registration_open: bool = True
    """Whether anyone may create an account, until an admin changes it in the application."""


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Build Settings from `env`, or from the process environment plus Backend/.env.

    Variables already set in the shell take precedence over Backend/.env.
    """
    if env is None:
        load_dotenv(ENV_FILE, override=False)
        env = os.environ

    model = _parse_model(env.get("SQL_AGENT_MODEL", DEFAULT_MODEL))
    return Settings(
        model=model,
        effort=_parse_effort(env.get("SQL_AGENT_EFFORT", DEFAULT_EFFORT), model),
        max_tokens=_parse_max_tokens(env.get("SQL_AGENT_MAX_TOKENS", str(DEFAULT_MAX_TOKENS))),
        db_path=_resolve_path(env.get("SQL_AGENT_DB_PATH", DEFAULT_DB_PATH)),
        csv_dir=_resolve_path(env.get("SQL_AGENT_CSV_DIR", DEFAULT_CSV_DIR)),
        as_of=_parse_as_of(env.get("SQL_AGENT_AS_OF_DATE", DEFAULT_AS_OF)),
        max_rows=_parse_int("SQL_AGENT_MAX_ROWS", env.get("SQL_AGENT_MAX_ROWS", str(DEFAULT_MAX_ROWS)), 1, 10_000),
        query_timeout_seconds=_parse_float("SQL_AGENT_QUERY_TIMEOUT", env.get("SQL_AGENT_QUERY_TIMEOUT", str(DEFAULT_QUERY_TIMEOUT)), 0.1, 300.0),
        log_path=_parse_log_path(env.get("SQL_AGENT_LOG_PATH", DEFAULT_LOG_PATH)),
        refusal_fallback=_parse_bool("SQL_AGENT_REFUSAL_FALLBACK", env.get("SQL_AGENT_REFUSAL_FALLBACK", "true")),
        cors_origins=_parse_origins(env.get("SQL_AGENT_CORS_ORIGINS", DEFAULT_CORS_ORIGINS)),
        request_log_path=_parse_log_path(env.get("SQL_AGENT_REQUEST_LOG_PATH", DEFAULT_REQUEST_LOG_PATH)),
        max_concurrent_runs=_parse_int(
            "SQL_AGENT_MAX_CONCURRENT_RUNS", env.get("SQL_AGENT_MAX_CONCURRENT_RUNS", str(DEFAULT_MAX_CONCURRENT_RUNS)), 1, 64
        ),
        daily_token_budget=_parse_int(
            "SQL_AGENT_DAILY_TOKEN_BUDGET", env.get("SQL_AGENT_DAILY_TOKEN_BUDGET", str(DEFAULT_DAILY_TOKEN_BUDGET)), 100_000, 10**10
        ),
        conversation_token_budget=_parse_int(
            "SQL_AGENT_CONVERSATION_TOKEN_BUDGET",
            env.get("SQL_AGENT_CONVERSATION_TOKEN_BUDGET", str(DEFAULT_CONVERSATION_TOKEN_BUDGET)),
            100_000,
            10**10,
        ),
        conversations_path=_parse_log_path(env.get("SQL_AGENT_CONVERSATIONS_PATH", DEFAULT_CONVERSATIONS_PATH)),
        store_result_rows=_parse_bool("SQL_AGENT_STORE_RESULT_ROWS", env.get("SQL_AGENT_STORE_RESULT_ROWS", "true")),
        analysis_max_rows=_parse_int(
            "SQL_AGENT_ANALYSIS_MAX_ROWS",
            env.get("SQL_AGENT_ANALYSIS_MAX_ROWS", str(DEFAULT_ANALYSIS_MAX_ROWS)),
            1,
            1_000_000,
        ),
        user_daily_token_budget=_parse_int(
            "SQL_AGENT_USER_DAILY_TOKEN_BUDGET",
            env.get("SQL_AGENT_USER_DAILY_TOKEN_BUDGET", str(DEFAULT_USER_DAILY_TOKEN_BUDGET)),
            100_000,
            10**10,
        ),
        secure_cookies=_parse_bool("SQL_AGENT_SECURE_COOKIES", env.get("SQL_AGENT_SECURE_COOKIES", "true")),
        public_url=_parse_public_url(env.get("SQL_AGENT_PUBLIC_URL", DEFAULT_PUBLIC_URL)),
        registration_open=_parse_registration(env.get("SQL_AGENT_REGISTRATION", "open")),
    )


def _parse_public_url(raw: str) -> str:
    value = raw.strip().rstrip("/")
    if not value.startswith(("http://", "https://")) or " " in value:
        raise ConfigError(f"SQL_AGENT_PUBLIC_URL must be an http or https address; got {raw!r}")
    return value


def _parse_registration(raw: str) -> bool:
    value = raw.strip().lower()
    if value not in ("open", "closed"):
        raise ConfigError(f"SQL_AGENT_REGISTRATION must be open or closed; got {raw!r}")
    return value == "open"


def _parse_model(raw: str) -> str:
    """The default model, which must be in the catalog in models.py, so it is in the picker."""
    value = raw.strip() or DEFAULT_MODEL
    if find_model(value) is None:
        offered = ", ".join(option.id for option in CATALOG)
        raise ConfigError(f"SQL_AGENT_MODEL must be one of {offered}; got {raw!r}")
    return value


def _parse_effort(raw: str, model: str = DEFAULT_MODEL) -> str:
    value = raw.strip().lower()
    if value not in VALID_EFFORTS:
        raise ConfigError(f"SQL_AGENT_EFFORT must be one of {', '.join(VALID_EFFORTS)}; got {raw!r}")
    option = find_model(model)
    if option is not None and value not in option.efforts:
        raise ConfigError(f"{option.label} does not offer {value} effort; choose one of {', '.join(option.efforts)}")
    return value


def _parse_max_tokens(raw: str) -> int:
    return _parse_int("SQL_AGENT_MAX_TOKENS", raw, 1, MAX_OUTPUT_TOKENS)


def _parse_int(name: str, raw: str, low: int, high: int) -> int:
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be an integer; got {raw!r}") from None
    if not low <= value <= high:
        raise ConfigError(f"{name} must be between {low} and {high}; got {value}")
    return value


def _parse_float(name: str, raw: str, low: float, high: float) -> float:
    try:
        value = float(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a number; got {raw!r}") from None
    if not low <= value <= high:
        raise ConfigError(f"{name} must be between {low} and {high}; got {value}")
    return value


def _resolve_path(raw: str) -> Path:
    """Relative paths resolve against the Backend folder, so the CLI works from any directory."""
    path = Path(raw.strip()).expanduser()
    return path if path.is_absolute() else (BACKEND_DIR / path).resolve()


def _parse_log_path(raw: str) -> Path | None:
    value = raw.strip()
    if value.lower() in ("", "off", "none"):
        return None
    return _resolve_path(value)


def _parse_as_of(raw: str) -> str:
    value = raw.strip().lower()
    if value in AS_OF_KEYWORDS:
        return value
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise ConfigError(f"SQL_AGENT_AS_OF_DATE must be 'latest', 'today' or YYYY-MM-DD; got {raw!r}") from None


def _parse_bool(name: str, raw: str) -> bool:
    value = raw.strip().lower()
    if value in ("1", "true", "yes", "on"):
        return True
    if value in ("0", "false", "no", "off"):
        return False
    raise ConfigError(f"{name} must be true or false; got {raw!r}")


def _parse_origins(raw: str) -> tuple[str, ...]:
    """Comma-separated origins such as http://localhost:4200. A wildcard is refused."""
    origins = tuple(part.strip().rstrip("/") for part in raw.split(",") if part.strip())
    for origin in origins:
        if origin == "*" or not origin.startswith(("http://", "https://")) or "/" in origin.split("://", 1)[1]:
            raise ConfigError(
                f"SQL_AGENT_CORS_ORIGINS must list origins such as http://localhost:4200; got {origin!r}"
            )
    return origins
