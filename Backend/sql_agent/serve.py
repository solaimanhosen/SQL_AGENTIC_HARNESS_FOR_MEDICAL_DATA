"""Run the HTTP service for the web interface.

Run from the Backend folder:

    .venv/bin/python -m sql_agent.serve                 # http://127.0.0.1:8000
    .venv/bin/python -m sql_agent.serve --port 8080

The interactive API documentation is served at /docs. Every endpoint except health and
sign-in needs an account's session. Session cookies travel over HTTPS only unless
SQL_AGENT_SECURE_COOKIES=false, which is for plain-HTTP use on this machine, so with it off
the service refuses to listen anywhere else.
"""

from __future__ import annotations

import argparse
import sys

import uvicorn

from .config import ConfigError, load_settings
from .conversations import NewerSchema
from .google_login import load_google_config
from .service import create_app

LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1", help="address to listen on (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="port to listen on (default: 8000)")
    args = parser.parse_args(argv)

    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"Settings error: {exc}", file=sys.stderr)
        return 1
    if not settings.db_path.exists():
        print(f"No database at {settings.db_path}. Build it with: python -m sql_agent.load_data", file=sys.stderr)
        return 1
    if args.host not in LOCAL_HOSTS and not settings.secure_cookies:
        print(
            f"Refusing to listen on {args.host} with SQL_AGENT_SECURE_COOKIES=false. Session cookies "
            "would cross the network unencrypted. Serve it behind HTTPS with secure cookies on.",
            file=sys.stderr,
        )
        return 1

    google = load_google_config(settings.public_url) is not None
    print(
        f"Accounts: registration {'open' if settings.registration_open else 'closed'} by default, "
        f"Google sign-in {'on' if google else 'off'}, cookies {'HTTPS only' if settings.secure_cookies else 'plain HTTP allowed'}.",
        file=sys.stderr,
    )
    try:
        app = create_app()
    except NewerSchema as exc:
        print(f"Conversations file error: {exc}", file=sys.stderr)
        return 1
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
