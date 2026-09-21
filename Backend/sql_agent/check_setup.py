"""Setup check: Python version, settings, read-only database access, API key, and one live Claude call.

Run from the Backend folder:
    .venv/bin/python -m sql_agent.check_setup            # full check, makes one small API call
    .venv/bin/python -m sql_agent.check_setup --offline  # skip the API call

The API key value is never printed, only whether it is set.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys

import anthropic

from .config import ENV_FILE, ConfigError, Settings, load_settings
from .llm import build_chat_model

MIN_PYTHON = (3, 10)
PING_PROMPT = "This is a connectivity check. Reply with exactly: OK"


def _report(status: str, label: str, detail: str = "") -> None:
    print(f"[{status}] {label}" + (f": {detail}" if detail else ""))


def check_python() -> bool:
    version = ".".join(map(str, sys.version_info[:3]))
    if sys.version_info[:2] < MIN_PYTHON:
        _report("FAIL", "Python", f"{version}; LangChain needs {'.'.join(map(str, MIN_PYTHON))}+")
        return False
    _report("PASS", "Python", version)
    return True


def check_database(settings: Settings) -> bool:
    path = settings.db_path
    if not path.exists():
        _report("FAIL", "Database", f"{path} not found. Build it with load_csv_to_sqlite.py")
        return False
    conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    try:
        # Internal tables such as sqlite_stat1, written by ANALYZE, are not part of the data.
        table_count = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchone()[0]
        latest = conn.execute("SELECT date(MAX(start)) FROM encounters").fetchone()[0]
    except sqlite3.Error as exc:
        _report("FAIL", "Database", f"{path.name} opened but could not be queried: {exc}")
        return False
    finally:
        conn.close()
    _report("PASS", "Database", f"{path.name} opened read-only, {table_count} tables, latest encounter {latest}")
    return True


def check_api_key() -> bool:
    if os.environ.get("ANTHROPIC_API_KEY", "").strip():
        _report("PASS", "ANTHROPIC_API_KEY", "set")
        return True
    hint = "add it to Backend/.env" if ENV_FILE.exists() else "copy .env.example to .env and add it there"
    _report("FAIL", "ANTHROPIC_API_KEY", f"not set; {hint}")
    return False


def check_live_call(settings: Settings) -> bool:
    model = build_chat_model(settings)
    try:
        reply = model.invoke(PING_PROMPT)
    except anthropic.AuthenticationError:
        detail = "the API key was rejected; check ANTHROPIC_API_KEY in Backend/.env"
    except anthropic.PermissionDeniedError:
        detail = "the API key is not allowed to use this model or feature"
    except anthropic.NotFoundError:
        detail = f"model {settings.model!r} was not found for this API key"
    except anthropic.RateLimitError:
        detail = "rate limited; wait a minute and retry"
    except anthropic.BadRequestError as exc:
        detail = f"request rejected: {exc.message}"
    except anthropic.APIStatusError as exc:
        detail = f"API error {exc.status_code}: {exc.message}"
    except anthropic.APIConnectionError:
        detail = "could not reach the Anthropic API; check the network connection"
    else:
        meta = reply.response_metadata
        usage = reply.usage_metadata or {}
        stop_reason = meta.get("stop_reason")
        served_by = meta.get("model_name") or meta.get("model") or settings.model
        if stop_reason == "refusal":
            _report("FAIL", "Claude call", f"{served_by} refused the connectivity prompt")
            return False
        _report(
            "PASS",
            "Claude call",
            f"{served_by} replied {reply.text.strip()!r} "
            f"(stop: {stop_reason}, tokens in/out: {usage.get('input_tokens')}/{usage.get('output_tokens')})",
        )
        return True
    _report("FAIL", "Claude call", detail)
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check that the SQL agent backend is set up correctly.")
    parser.add_argument("--offline", action="store_true", help="skip the live Claude API call")
    args = parser.parse_args(argv)

    results = [check_python()]
    try:
        settings = load_settings()
    except ConfigError as exc:
        _report("FAIL", "Settings", str(exc))
        return 1
    _report(
        "PASS",
        "Settings",
        f"model {settings.model}, effort {settings.effort}, max_tokens {settings.max_tokens}, "
        f"as-of {settings.as_of}, refusal fallback {'on' if settings.refusal_fallback else 'off'}",
    )
    results.append(check_database(settings))
    key_ok = check_api_key()
    results.append(key_ok)

    if args.offline:
        _report("SKIP", "Claude call", "--offline")
    elif key_ok:
        results.append(check_live_call(settings))
    else:
        _report("SKIP", "Claude call", "no API key")

    all_ok = all(results)
    print("\nSetup OK." if all_ok else "\nSetup incomplete; fix the FAIL lines above.")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
