"""Who is asking: the session cookie, the checks against cross-site requests, and sign-in throttling.

The browser holds the session token in an HttpOnly cookie, so page scripts cannot read it,
and it is sent only to /api. A cookie is sent with any request to the site, so a request
that changes something must also prove it came from our own pages: it carries the header
`X-Requested-With: sql-agent`, which a page on another site cannot send without the CORS
check passing, and any Origin it names must be one we allow.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Iterable

from fastapi import Request
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .accounts import AccountStore, User

SESSION_COOKIE = "sql_agent_session"
CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "sql-agent"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class NotSignedIn(Exception):
    """No valid session came with the request."""


class NotAllowed(Exception):
    """Signed in, but this needs the admin role."""


class Throttled(Exception):
    """Too many failed sign-ins, or too many emails asked for, recently."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def set_session_cookie(response, token: str, *, secure: bool) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=90 * 24 * 3600,
        path="/api",
        httponly=True,
        secure=secure,
        samesite="strict",
    )


def clear_session_cookie(response, *, secure: bool) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/api", httponly=True, secure=secure, samesite="strict")


class Sessions:
    """FastAPI dependencies that resolve the signed-in user."""

    def __init__(self, accounts: AccountStore) -> None:
        self.accounts = accounts

    def current(self, request: Request) -> User:
        resolved = self.accounts.resolve_session(request.cookies.get(SESSION_COOKIE))
        if resolved is None:
            raise NotSignedIn()
        user, session_id = resolved
        request.state.user_id = user.id
        request.state.session_id = session_id
        return user

    def admin(self, request: Request) -> User:
        user = self.current(request)
        if not user.is_admin:
            raise NotAllowed()
        return user


class CsrfGuard:
    """Refuse requests that change something unless they came from our own pages."""

    def __init__(self, app: ASGIApp, allowed_origins: Iterable[str]) -> None:
        self.app = app
        self.allowed_origins = frozenset(allowed_origins)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] in SAFE_METHODS:
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        origin = headers.get("origin")
        if headers.get(CSRF_HEADER) != CSRF_VALUE or (origin is not None and origin not in self._own(scope, origin)):
            scope.setdefault("state", {})["refused"] = "cross_site"
            response = JSONResponse(
                status_code=403,
                content={"error": "cross_site", "message": "This request did not come from the application."},
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)

    def _own(self, scope: Scope, origin: str) -> frozenset[str]:
        """The configured origins, plus the service's own, for a page it served itself."""
        host = Headers(scope=scope).get("host")
        own = {f"{scope.get('scheme', 'http')}://{host}"} if host else set()
        return self.allowed_origins | own


class SignInThrottle:
    """Failed sign-ins per address and per email over a sliding window, kept in memory.

    The same counting limits the emails anyone can make the service send.
    """

    def __init__(
        self,
        *,
        per_address: int = 20,
        per_email: int = 10,
        window_seconds: float = 600.0,
        message: str = "Too many failed sign-ins. Wait a few minutes and try again.",
    ) -> None:
        self.limits = {"address": per_address, "email": per_email}
        self.window = window_seconds
        self.message = message
        self._failures: dict[tuple[str, str], deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, address: str, email: str) -> None:
        now = time.monotonic()
        with self._lock:
            for key in (("address", address), ("email", email.strip().lower())):
                if len(self._recent(key, now)) >= self.limits[key[0]]:
                    raise Throttled(self.message)

    def failed(self, address: str, email: str) -> None:
        now = time.monotonic()
        with self._lock:
            for key in (("address", address), ("email", email.strip().lower())):
                self._recent(key, now).append(now)

    def succeeded(self, email: str) -> None:
        with self._lock:
            self._failures.pop(("email", email.strip().lower()), None)

    def _recent(self, key: tuple[str, str], now: float) -> deque[float]:
        times = self._failures.setdefault(key, deque())
        while times and now - times[0] > self.window:
            times.popleft()
        return times
