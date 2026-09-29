"""Run the HTTP service for the web interface.

Run from the Backend folder:

    .venv/bin/python -m sql_agent.serve                 # http://127.0.0.1:8000
    .venv/bin/python -m sql_agent.serve --port 8080

The interactive API documentation is served at /docs. Without SQL_AGENT_API_TOKEN the
service is open, so it refuses to listen anywhere but this machine. With a token, clients
send it as a bearer token and --host may name another address.
"""

from __future__ import annotations

import argparse
import sys

import uvicorn

from .config import ConfigError, load_api_token, load_settings
from .service import create_app

LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1", help="address to listen on (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="port to listen on (default: 8000)")
    args = parser.parse_args(argv)

    try:
        settings = load_settings()
        api_token = load_api_token()
    except ConfigError as exc:
        print(f"Settings error: {exc}", file=sys.stderr)
        return 1
    if not settings.db_path.exists():
        print(f"No database at {settings.db_path}. Build it with: python -m sql_agent.load_data", file=sys.stderr)
        return 1
    if args.host not in LOCAL_HOSTS and api_token is None:
        print(
            f"Refusing to listen on {args.host} without SQL_AGENT_API_TOKEN. Anyone who could "
            "reach it could ask questions at your expense. Set a token in Backend/.env first.",
            file=sys.stderr,
        )
        return 1

    print(f"Access token {'required' if api_token else 'not set, open to this machine only'}.", file=sys.stderr)
    uvicorn.run(create_app(api_token=api_token), host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
