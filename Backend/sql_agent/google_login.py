"""Signing in with Google, by OpenID Connect's authorization code flow with PKCE.

1. `start` stores a one-time state, a nonce and a PKCE verifier, puts the state in a short
   cookie, and sends the browser to Google.
2. Google sends the browser back to the callback with a code and the state. The state must
   match the cookie and a stored, unused, recent sign-in.
3. The code is exchanged with Google's token endpoint, server to server, with our client
   secret and the PKCE verifier. The ID token in the reply is read directly: it came from
   Google over HTTPS to a request authenticated with our secret, which OpenID Connect
   (section 3.1.3.7) allows in place of checking its signature. Its issuer, audience,
   expiry, nonce and verified email are still checked.
4. Which account it reaches is decided by `resolve_account`, which never links Google to an
   account whose email nobody verified (ADR 0007).
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from .accounts import AccountError, AccountStore, User

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
ISSUERS = frozenset({"accounts.google.com", "https://accounts.google.com"})
CALLBACK_PATH = "/api/auth/google/callback"
STATE_COOKIE = "sql_agent_oauth"
STATE_COOKIE_PATH = "/api/auth/google"


class GoogleLoginError(Exception):
    """The sign-in did not complete. `code` goes to the login page; details stay here."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code


@dataclass(frozen=True)
class GoogleConfig:
    client_id: str
    client_secret: str
    redirect_uri: str


@dataclass(frozen=True)
class GoogleIdentity:
    sub: str
    email: str
    name: str


def load_google_config(public_url: str, env: Mapping[str, str] | None = None) -> GoogleConfig | None:
    """The OAuth client from SQL_AGENT_GOOGLE_CLIENT_ID and _SECRET, or None when either is unset.

    The secret is read here and kept out of Settings, like the Anthropic key, so printing the
    settings can never show it.
    """
    env = os.environ if env is None else env
    client_id = env.get("SQL_AGENT_GOOGLE_CLIENT_ID", "").strip()
    client_secret = env.get("SQL_AGENT_GOOGLE_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        return None
    return GoogleConfig(client_id, client_secret, public_url.rstrip("/") + CALLBACK_PATH)


def safe_next(path: str | None) -> str:
    """A path inside this application to return to, so sign-in cannot redirect elsewhere."""
    if (
        not path
        or len(path) > 500
        or not path.startswith("/")
        or path.startswith(("//", "/\\", "/api"))
        or any(ord(char) < 32 for char in path)
    ):
        return "/"
    return path


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def begin(accounts: AccountStore, config: GoogleConfig, *, next_path: str, link_user_id: str | None) -> tuple[str, str]:
    """Record a pending sign-in. Returns the state for the cookie and the URL to send the browser to."""
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    accounts.save_oauth_state(
        state, nonce=nonce, code_verifier=verifier, next_path=safe_next(next_path), link_user_id=link_user_id
    )
    query = urlencode(
        {
            "client_id": config.client_id,
            "redirect_uri": config.redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "nonce": nonce,
            "code_challenge": _b64url(hashlib.sha256(verifier.encode("ascii")).digest()),
            "code_challenge_method": "S256",
            "prompt": "select_account",
        }
    )
    return state, f"{AUTHORIZE_URL}?{query}"


TokenExchange = Callable[[GoogleConfig, str, str], Mapping]


def exchange_code(config: GoogleConfig, code: str, verifier: str) -> Mapping:
    """Google's token response for this code. Any failure is a GoogleLoginError."""
    try:
        response = httpx.post(
            TOKEN_URL,
            data={
                "code": code,
                "client_id": config.client_id,
                "client_secret": config.client_secret,
                "redirect_uri": config.redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": verifier,
            },
            timeout=10.0,
        )
    except httpx.HTTPError as exc:
        raise GoogleLoginError("google_unreachable", str(exc)) from None
    if response.status_code != 200:
        raise GoogleLoginError("google_refused", f"token endpoint answered {response.status_code}")
    return response.json()


def identity_from(tokens: Mapping, config: GoogleConfig, *, nonce: str, now: float | None = None) -> GoogleIdentity:
    """Check the ID token's claims and return who it names."""
    try:
        payload = tokens["id_token"].split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (KeyError, IndexError, ValueError, AttributeError):
        raise GoogleLoginError("invalid_token", "no readable ID token") from None
    now = time.time() if now is None else now
    checks = {
        "issuer": claims.get("iss") in ISSUERS,
        "audience": claims.get("aud") == config.client_id,
        "expiry": isinstance(claims.get("exp"), (int, float)) and claims["exp"] > now,
        "nonce": isinstance(claims.get("nonce"), str) and secrets.compare_digest(claims["nonce"], nonce),
        "subject": isinstance(claims.get("sub"), str) and bool(claims["sub"]),
        "email": isinstance(claims.get("email"), str) and bool(claims["email"]),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise GoogleLoginError("invalid_token", "failed: " + ", ".join(failed))
    if claims.get("email_verified") is not True:
        raise GoogleLoginError("email_unverified", "Google has not verified this email")
    return GoogleIdentity(sub=claims["sub"], email=claims["email"], name=str(claims.get("name") or ""))


def resolve_account(
    accounts: AccountStore, identity: GoogleIdentity, *, link_user_id: str | None, registration_open: bool
) -> User:
    """The account this Google identity signs in to, linking or creating one when allowed."""
    known = accounts.find_by_google(identity.sub)
    if link_user_id is not None:
        # Connecting Google from Account settings, while signed in.
        if known is not None and known.id != link_user_id:
            raise GoogleLoginError("google_in_use")
        user = known or _link(accounts, link_user_id, identity.sub)
    elif known is not None:
        user = known
    else:
        same_email = accounts.find_by_email(identity.email)
        if same_email is not None:
            # Only an email somebody verified may be linked. A self-registered account was
            # never checked, so linking it would hand it to whoever registered that email.
            if not same_email.email_verified:
                raise GoogleLoginError("link_required")
            user = _link(accounts, same_email.id, identity.sub)
        elif not registration_open:
            raise GoogleLoginError("registration_closed")
        else:
            user = accounts.create_user(
                identity.email, name=identity.name, email_verified=True, google_sub=identity.sub
            )
    if user.disabled:
        raise GoogleLoginError("disabled")
    return user


def _link(accounts: AccountStore, user_id: str, sub: str) -> User:
    try:
        return accounts.link_google(user_id, sub)
    except AccountError as exc:
        raise GoogleLoginError(exc.kind) from None
