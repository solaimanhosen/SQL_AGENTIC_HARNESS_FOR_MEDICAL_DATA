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

BACKEND_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BACKEND_DIR / ".env"

DEFAULT_MODEL = "claude-opus-5"
DEFAULT_EFFORT = "high"
DEFAULT_MAX_TOKENS = 16_000
DEFAULT_DB_PATH = "synthea.db"
DEFAULT_AS_OF = "latest"

VALID_EFFORTS = ("low", "medium", "high", "xhigh", "max")
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
    as_of: str
    """Anchor for relative time windows such as "last 12 months" (see docs/decisions/0002).

    "latest" means the last encounter date in the data, "today" means the real
    current date, and a YYYY-MM-DD value pins an explicit date.
    """
    refusal_fallback: bool


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Build Settings from `env`, or from the process environment plus Backend/.env.

    Variables already set in the shell take precedence over Backend/.env.
    """
    if env is None:
        load_dotenv(ENV_FILE, override=False)
        env = os.environ

    return Settings(
        model=env.get("SQL_AGENT_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL,
        effort=_parse_effort(env.get("SQL_AGENT_EFFORT", DEFAULT_EFFORT)),
        max_tokens=_parse_max_tokens(env.get("SQL_AGENT_MAX_TOKENS", str(DEFAULT_MAX_TOKENS))),
        db_path=_resolve_db_path(env.get("SQL_AGENT_DB_PATH", DEFAULT_DB_PATH)),
        as_of=_parse_as_of(env.get("SQL_AGENT_AS_OF_DATE", DEFAULT_AS_OF)),
        refusal_fallback=_parse_bool("SQL_AGENT_REFUSAL_FALLBACK", env.get("SQL_AGENT_REFUSAL_FALLBACK", "true")),
    )


def _parse_effort(raw: str) -> str:
    value = raw.strip().lower()
    if value not in VALID_EFFORTS:
        raise ConfigError(f"SQL_AGENT_EFFORT must be one of {', '.join(VALID_EFFORTS)}; got {raw!r}")
    return value


def _parse_max_tokens(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"SQL_AGENT_MAX_TOKENS must be an integer; got {raw!r}") from None
    if not 1 <= value <= MAX_OUTPUT_TOKENS:
        raise ConfigError(f"SQL_AGENT_MAX_TOKENS must be between 1 and {MAX_OUTPUT_TOKENS}; got {value}")
    return value


def _resolve_db_path(raw: str) -> Path:
    """Relative paths resolve against the Backend folder, so the CLI works from any directory."""
    path = Path(raw.strip()).expanduser()
    return path if path.is_absolute() else (BACKEND_DIR / path).resolve()


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
