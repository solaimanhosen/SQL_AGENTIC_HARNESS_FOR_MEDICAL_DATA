"""One line per HTTP request, as JSON Lines, next to the run log.

The run log in runlog.py records what each answered question did. This log records who
asked what of the service and how it went, including the requests that were refused: a
missing token, an oversized body, a spending limit. Together they answer both "what did the
agent do" and "what was the service asked to do".

No request or response bodies are written, and neither is the Authorization header. The
question already lives in the run log, keyed by conversation.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from starlette.types import ASGIApp, Message, Receive, Scope, Send


class RequestLogMiddleware:
    """ASGI middleware that appends a record when each HTTP response finishes."""

    def __init__(self, app: ASGIApp, path: Path) -> None:
        self.app = app
        self.path = path
        self._lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = time.perf_counter()
        status = 500

        async def send_and_watch(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_and_watch)
        finally:
            client = scope.get("client")
            self.write(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "method": scope.get("method"),
                    "path": scope.get("path"),
                    "status": status,
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
                    "client": client[0] if client else None,
                    "authenticated": bool(scope.get("state", {}).get("authenticated", False)),
                    "refused": scope.get("state", {}).get("refused"),
                }
            )

    def write(self, record: dict) -> None:
        line = json.dumps(record, ensure_ascii=False) + "\n"
        with self._lock, self.path.open("a", encoding="utf-8") as handle:
            handle.write(line)
