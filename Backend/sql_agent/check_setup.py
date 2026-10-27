"""Setup check: Python version, settings, read-only database access, API key, one live Claude call,
and the mail server if email is set up.

Run from the Backend folder:
    .venv/bin/python -m sql_agent.check_setup               # full check, makes one small API call
    .venv/bin/python -m sql_agent.check_setup --offline     # skip every API call
    .venv/bin/python -m sql_agent.check_setup --all-models  # one small call to every model offered

The API key and the mail password are never printed, only whether they are set.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys

import anthropic

from .config import ENV_FILE, ConfigError, Settings, load_settings
from .llm import build_chat_model
from .mailer import MailError, load_mailer
from .models import CATALOG

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


def catalog_problems(listed: list[dict]) -> list[str]:
    """What the Models API says that disagrees with the catalog in models.py.

    `listed` is the API's model list as dictionaries. Each model offered must be listed, must
    accept adaptive thinking, and must accept every effort the picker offers for it.
    """
    by_id = {item["id"]: item for item in listed}
    problems = []
    for option in CATALOG:
        item = by_id.get(option.id)
        if item is None:
            problems.append(f"{option.id} is not offered to this API key")
            continue
        capabilities = item.get("capabilities") or {}
        thinking = (capabilities.get("thinking") or {}).get("types") or {}
        if not (thinking.get("adaptive") or {}).get("supported"):
            problems.append(f"{option.id} does not accept adaptive thinking")
        effort = capabilities.get("effort") or {}
        missing = [level for level in option.efforts if not (effort.get(level) or {}).get("supported")]
        if missing:
            problems.append(f"{option.id} does not accept effort {', '.join(missing)}")
    return problems


def check_model_catalog() -> bool:
    """Every model the picker offers is available, with the efforts offered. No tokens are used."""
    try:
        listed = [model.model_dump() for model in anthropic.Anthropic().models.list(limit=100)]
    except anthropic.APIError as exc:
        _report("FAIL", "Models offered", f"the model list could not be read: {exc}")
        return False
    problems = catalog_problems(listed)
    if problems:
        _report("FAIL", "Models offered", "; ".join(problems))
        return False
    _report("PASS", "Models offered", f"all {len(CATALOG)} available with every effort offered")
    return True


def check_live_call(settings: Settings, model_id: str | None = None) -> bool:
    model_id = model_id or settings.model
    model = build_chat_model(settings, model=model_id)
    try:
        reply = model.invoke(PING_PROMPT)
    except anthropic.AuthenticationError:
        detail = "the API key was rejected; check ANTHROPIC_API_KEY in Backend/.env"
    except anthropic.PermissionDeniedError:
        detail = "the API key is not allowed to use this model or feature"
    except anthropic.NotFoundError:
        detail = f"model {model_id!r} was not found for this API key"
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
        served_by = meta.get("model_name") or meta.get("model") or model_id
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


def check_email(*, offline: bool) -> bool:
    """Sign in to the mail server without sending anything. Email being off is not a failure."""
    try:
        mailer = load_mailer()
    except ConfigError as exc:
        _report("FAIL", "Email", str(exc))
        return False
    if mailer is None:
        _report("SKIP", "Email", "off; set SQL_AGENT_SMTP_* to send password reset links")
        return True
    where = f"{mailer.host}:{mailer.port} as {mailer.username}"
    if offline:
        _report("SKIP", "Email", f"{where}, not contacted with --offline")
        return True
    try:
        mailer.check()
    except MailError as exc:
        _report("FAIL", "Email", f"{where}: {exc}")
        return False
    _report("PASS", "Email", f"signed in to {where}")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check that the SQL agent backend is set up correctly.")
    parser.add_argument("--offline", action="store_true", help="skip every call to the Anthropic API")
    parser.add_argument(
        "--all-models", action="store_true", help="make the small live call on every model offered, not just the default"
    )
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
        _report("SKIP", "Models offered", "--offline")
        _report("SKIP", "Claude call", "--offline")
    elif key_ok:
        results.append(check_model_catalog())
        for model_id in [option.id for option in CATALOG] if args.all_models else [settings.model]:
            results.append(check_live_call(settings, model_id))
    else:
        _report("SKIP", "Claude call", "no API key")

    results.append(check_email(offline=args.offline))

    all_ok = all(results)
    print("\nSetup OK." if all_ok else "\nSetup incomplete; fix the FAIL lines above.")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
