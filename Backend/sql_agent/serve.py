"""Run the HTTP service for the web interface.

Run from the Backend folder:

    .venv/bin/python -m sql_agent.serve                 # http://127.0.0.1:8000
    .venv/bin/python -m sql_agent.serve --port 8080

The interactive API documentation is served at /docs. The service has no access control
yet, so it listens on this machine only unless told otherwise.
"""

from __future__ import annotations

import argparse
import sys

import uvicorn

from .config import ConfigError, load_settings
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
    if args.host not in LOCAL_HOSTS:
        print(
            f"Warning: listening on {args.host} with no access control. Anyone who can reach "
            "this address can ask questions at your expense.",
            file=sys.stderr,
        )

    uvicorn.run(create_app(), host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
