"""User accounts, sign-in sessions and pending Google sign-ins, in the application database.

Two roles exist: `user` and `admin`. An account has a password, a linked Google identity, or
both. Its email counts as verified only when Google said so, an admin created it, or its
owner opened a link sent to it; that decides whether a Google sign-in may be linked to it
(see ADRs 0007 and 0009).

A session is a random token held by the browser in an HttpOnly cookie. Only its SHA-256 is
stored, so a copy of the database does not let anyone sign in. A session ends after 30 days
unused or 90 days in all, when its user is disabled, or when it is revoked.

A link sent by email carries a token of the same kind, again stored only as its hash. It
works once, for one purpose, and only until it expires; a newer link for the same purpose
replaces it.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .appdb import AppDatabase
from .passwords import check_rules, hash_password, verify_password

ROLES = ("user", "admin")
MAX_EMAIL_CHARS = 254
MAX_NAME_CHARS = 100
SESSION_IDLE = timedelta(days=30)
SESSION_LIFETIME = timedelta(days=90)
# Writing the time of every request would turn each read into a write.
SESSION_TOUCH_EVERY = timedelta(minutes=5)
OAUTH_STATE_LIFETIME = timedelta(minutes=10)
# Short for a reset, since the link alone sets a password; longer for confirming an address.
EMAIL_TOKEN_LIFETIMES = {"reset": timedelta(minutes=30), "verify": timedelta(days=3)}
INVALID_LINK = "This link has expired or was already used. Ask for a new one."
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AccountError(ValueError):
    """Something about an account request is not allowed. `kind` is a short code for callers."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message


@dataclass(frozen=True)
class User:
    id: str
    email: str
    name: str
    role: str
    has_password: bool
    google_linked: bool
    email_verified: bool
    disabled: bool
    default_model: str | None
    default_effort: str | None
    created_at: str
    last_seen_at: str | None

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


@dataclass(frozen=True)
class SessionInfo:
    id: str
    created_at: str
    last_used_at: str
    expires_at: str
    user_agent: str


@dataclass(frozen=True)
class OAuthState:
    nonce: str
    code_verifier: str
    next_path: str
    link_user_id: str | None


def normalize_email(email: str) -> str:
    email = email.strip().lower()
    if len(email) > MAX_EMAIL_CHARS or not EMAIL_PATTERN.match(email):
        raise AccountError("invalid_email", "Enter a valid email address.")
    return email


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class AccountStore:
    def __init__(self, database: AppDatabase, *, now: Callable[[], datetime] | None = None) -> None:
        self.database = database
        self._db = database.connection
        self._lock = database.lock
        self._now = now or (lambda: datetime.now(timezone.utc))

    # Users -----------------------------------------------------------------------------

    def create_user(
        self,
        email: str,
        *,
        password: str | None = None,
        name: str = "",
        role: str = "user",
        email_verified: bool = False,
        google_sub: str | None = None,
    ) -> User:
        email = normalize_email(email)
        if role not in ROLES:
            raise AccountError("invalid_role", f"A role is one of {', '.join(ROLES)}.")
        if password is not None:
            check_rules(password)
        password_hash = hash_password(password) if password is not None else None
        user_id = secrets.token_hex(16)
        with self._lock:
            try:
                self._db.execute(
                    "INSERT INTO users (id, email, name, role, password_hash, google_sub, email_verified, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        user_id,
                        email,
                        name.strip()[:MAX_NAME_CHARS],
                        role,
                        password_hash,
                        google_sub,
                        int(email_verified),
                        self._stamp(),
                    ),
                )
            except sqlite3.IntegrityError:
                raise AccountError("email_taken", "An account with this email already exists.") from None
            return self._user_row("id", user_id)

    def get_user(self, user_id: str) -> User | None:
        with self._lock:
            return self._user_row("id", user_id)

    def find_by_email(self, email: str) -> User | None:
        try:
            email = normalize_email(email)
        except AccountError:
            return None
        with self._lock:
            return self._user_row("email", email)

    def find_by_google(self, google_sub: str) -> User | None:
        with self._lock:
            return self._user_row("google_sub", google_sub)

    def list_users(self) -> list[User]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM users ORDER BY created_at").fetchall()
            return [_user(row) for row in rows]

    def authenticate(self, email: str, password: str) -> User | None:
        """The user, if the email and password match an enabled account. Otherwise None.

        The time taken does not depend on whether the account exists or has a password.
        """
        try:
            email = normalize_email(email)
        except AccountError:
            email = ""
        with self._lock:
            row = self._db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone() if email else None
        stored = row["password_hash"] if row is not None else None
        if not verify_password(password, stored) or row is None or row["disabled"]:
            return None
        return _user(row)

    def update_profile(
        self,
        user_id: str,
        *,
        name: str | None = None,
        default_model: str | None = None,
        default_effort: str | None = None,
        clear_default_model: bool = False,
    ) -> User:
        with self._lock:
            if name is not None:
                self._db.execute("UPDATE users SET name = ? WHERE id = ?", (name.strip()[:MAX_NAME_CHARS], user_id))
            if clear_default_model:
                self._db.execute("UPDATE users SET default_model = NULL, default_effort = NULL WHERE id = ?", (user_id,))
            elif default_model is not None:
                self._db.execute(
                    "UPDATE users SET default_model = ?, default_effort = ? WHERE id = ?",
                    (default_model, default_effort, user_id),
                )
            return self._require(user_id)

    def change_password(self, user_id: str, new: str, *, current: str | None) -> None:
        """Set a new password. An account that already has one must give it as `current`."""
        check_rules(new)
        with self._lock:
            row = self._db.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            raise AccountError("unknown_user", "No such account.")
        if row["password_hash"] is not None and not verify_password(current or "", row["password_hash"]):
            raise AccountError("wrong_password", "The current password is not correct.")
        with self._lock:
            self._db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(new), user_id))
            self._void_email_tokens(user_id, "reset")

    def reset_password(self, user_id: str, new: str) -> None:
        """Set a password without the old one, for an admin. Every session of the user ends."""
        check_rules(new)
        with self._lock:
            self._require(user_id)
            self._db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(new), user_id))
            self._db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
            self._void_email_tokens(user_id, "reset")

    def set_role(self, user_id: str, role: str) -> User:
        if role not in ROLES:
            raise AccountError("invalid_role", f"A role is one of {', '.join(ROLES)}.")
        with self._lock:
            self._require(user_id)
            self._db.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
            return self._require(user_id)

    def set_disabled(self, user_id: str, disabled: bool) -> User:
        """Disable or enable. Disabling ends every session at once."""
        with self._lock:
            self._require(user_id)
            self._db.execute("UPDATE users SET disabled = ? WHERE id = ?", (int(disabled), user_id))
            if disabled:
                self._db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
            return self._require(user_id)

    def link_google(self, user_id: str, google_sub: str) -> User:
        """Attach a Google identity. Its email has then been verified by Google."""
        with self._lock:
            try:
                self._db.execute(
                    "UPDATE users SET google_sub = ?, email_verified = 1 WHERE id = ?", (google_sub, user_id)
                )
            except sqlite3.IntegrityError:
                raise AccountError("google_in_use", "This Google account is linked to another account.") from None
            return self._require(user_id)

    def unlink_google(self, user_id: str) -> User:
        """Detach Google. Refused for an account with no password, which could not sign in after."""
        with self._lock:
            user = self._require(user_id)
            if not user.has_password:
                raise AccountError("needs_password", "Set a password before disconnecting Google.")
            self._db.execute("UPDATE users SET google_sub = NULL WHERE id = ?", (user_id,))
            return self._require(user_id)

    # Sessions --------------------------------------------------------------------------

    def create_session(self, user_id: str, *, user_agent: str = "") -> str:
        """Start a session and return its token, which only the browser keeps."""
        token = secrets.token_urlsafe(32)
        now = self._now()
        with self._lock:
            self._db.execute(
                "INSERT INTO sessions (id, token_hash, user_id, created_at, last_used_at, expires_at, user_agent)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    secrets.token_hex(8),
                    _token_hash(token),
                    user_id,
                    now.isoformat(),
                    now.isoformat(),
                    (now + SESSION_LIFETIME).isoformat(),
                    user_agent[:200],
                ),
            )
            self._db.execute("UPDATE users SET last_seen_at = ? WHERE id = ?", (now.isoformat(), user_id))
        return token

    def resolve_session(self, token: str | None) -> tuple[User, str] | None:
        """The user and session id a token belongs to, or None if it is unknown, ended or disabled."""
        if not token:
            return None
        now = self._now()
        with self._lock:
            row = self._db.execute("SELECT * FROM sessions WHERE token_hash = ?", (_token_hash(token),)).fetchone()
            if row is None:
                return None
            last_used = datetime.fromisoformat(row["last_used_at"])
            if now >= datetime.fromisoformat(row["expires_at"]) or now - last_used >= SESSION_IDLE:
                self._db.execute("DELETE FROM sessions WHERE id = ?", (row["id"],))
                return None
            user = self._user_row("id", row["user_id"])
            if user is None or user.disabled:
                return None
            if now - last_used >= SESSION_TOUCH_EVERY:
                self._db.execute("UPDATE sessions SET last_used_at = ? WHERE id = ?", (now.isoformat(), row["id"]))
                self._db.execute("UPDATE users SET last_seen_at = ? WHERE id = ?", (now.isoformat(), user.id))
            return user, row["id"]

    def end_session(self, token: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))

    def list_sessions(self, user_id: str) -> list[SessionInfo]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM sessions WHERE user_id = ? ORDER BY last_used_at DESC", (user_id,)
            ).fetchall()
            return [
                SessionInfo(row["id"], row["created_at"], row["last_used_at"], row["expires_at"], row["user_agent"])
                for row in rows
            ]

    def revoke_session(self, user_id: str, session_id: str) -> bool:
        """End one of the user's own sessions. False if they have none with that id."""
        with self._lock:
            return (
                self._db.execute("DELETE FROM sessions WHERE id = ? AND user_id = ?", (session_id, user_id)).rowcount
                > 0
            )

    def revoke_other_sessions(self, user_id: str, keep_session_id: str) -> int:
        with self._lock:
            return self._db.execute(
                "DELETE FROM sessions WHERE user_id = ? AND id != ?", (user_id, keep_session_id)
            ).rowcount

    # Pending Google sign-ins -------------------------------------------------------------

    def save_oauth_state(
        self, state: str, *, nonce: str, code_verifier: str, next_path: str, link_user_id: str | None
    ) -> None:
        now = self._now()
        with self._lock:
            # Old ones that were never completed are cleared on the way.
            self._db.execute(
                "DELETE FROM oauth_states WHERE created_at < ?", ((now - OAUTH_STATE_LIFETIME).isoformat(),)
            )
            self._db.execute(
                "INSERT INTO oauth_states VALUES (?, ?, ?, ?, ?, ?)",
                (_token_hash(state), nonce, code_verifier, next_path, link_user_id, now.isoformat()),
            )

    def take_oauth_state(self, state: str) -> OAuthState | None:
        """The pending sign-in for this state, removed so it can be used only once."""
        now = self._now()
        with self._lock:
            row = self._db.execute("SELECT * FROM oauth_states WHERE state_hash = ?", (_token_hash(state),)).fetchone()
            if row is None:
                return None
            self._db.execute("DELETE FROM oauth_states WHERE state_hash = ?", (row["state_hash"],))
        if now - datetime.fromisoformat(row["created_at"]) > OAUTH_STATE_LIFETIME:
            return None
        return OAuthState(row["nonce"], row["code_verifier"], row["next_path"], row["link_user_id"])

    # Links sent by email ------------------------------------------------------------------

    def issue_email_token(self, user_id: str, purpose: str) -> str:
        """A token for a link that resets the password (`reset`) or confirms the email (`verify`).

        Only the browser that opens the link sees the token; its hash is stored. An earlier
        unused link for the same purpose stops working.
        """
        lifetime = EMAIL_TOKEN_LIFETIMES[purpose]
        token = secrets.token_urlsafe(32)
        now = self._now()
        with self._lock:
            self._require(user_id)
            self._void_email_tokens(user_id, purpose)
            # Expired links of anyone are cleared on the way.
            self._db.execute("DELETE FROM email_tokens WHERE expires_at < ?", (now.isoformat(),))
            self._db.execute(
                "INSERT INTO email_tokens (token_hash, user_id, purpose, created_at, expires_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (_token_hash(token), user_id, purpose, now.isoformat(), (now + lifetime).isoformat()),
            )
        return token

    def use_reset_token(self, token: str, new_password: str) -> User:
        """Set a password from a reset link. Every session ends, and the email counts as verified.

        Opening the link proves its reader holds the mailbox. A password that breaks the rules
        is refused before the link is used, so the person can try again with the same link.
        """
        check_rules(new_password)
        user = self._take_email_token(token, "reset")
        with self._lock:
            self._db.execute(
                "UPDATE users SET password_hash = ?, email_verified = 1 WHERE id = ?",
                (hash_password(new_password), user.id),
            )
            self._db.execute("DELETE FROM sessions WHERE user_id = ?", (user.id,))
            return self._require(user.id)

    def use_verify_token(self, token: str) -> User:
        """Mark the email as verified, from a confirmation link."""
        user = self._take_email_token(token, "verify")
        with self._lock:
            self._db.execute("UPDATE users SET email_verified = 1 WHERE id = ?", (user.id,))
            return self._require(user.id)

    def _take_email_token(self, token: str, purpose: str) -> User:
        """The enabled account a link is for, with the link removed so it works only once."""
        now = self._now()
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM email_tokens WHERE token_hash = ? AND purpose = ?", (_token_hash(token), purpose)
            ).fetchone()
            if row is not None:
                self._db.execute("DELETE FROM email_tokens WHERE token_hash = ?", (row["token_hash"],))
            user = None if row is None else self._user_row("id", row["user_id"])
        if row is None or now >= datetime.fromisoformat(row["expires_at"]) or user is None or user.disabled:
            raise AccountError("invalid_link", INVALID_LINK)
        return user

    def _void_email_tokens(self, user_id: str, purpose: str) -> None:
        """Called with the lock held."""
        self._db.execute("DELETE FROM email_tokens WHERE user_id = ? AND purpose = ?", (user_id, purpose))

    # Settings ---------------------------------------------------------------------------

    def registration_open(self, default: bool = True) -> bool:
        with self._lock:
            row = self._db.execute("SELECT value FROM app_settings WHERE key = 'registration'").fetchone()
        return default if row is None else row["value"] == "open"

    def set_registration(self, open_: bool) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO app_settings (key, value) VALUES ('registration', ?)"
                " ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                ("open" if open_ else "closed",),
            )

    # Internals --------------------------------------------------------------------------

    def _stamp(self) -> str:
        return self._now().isoformat()

    def _user_row(self, column: str, value: str) -> User | None:
        row = self._db.execute(f"SELECT * FROM users WHERE {column} = ?", (value,)).fetchone()  # noqa: S608
        return None if row is None else _user(row)

    def _require(self, user_id: str) -> User:
        user = self._user_row("id", user_id)
        if user is None:
            raise AccountError("unknown_user", "No such account.")
        return user


def _user(row: sqlite3.Row) -> User:
    return User(
        id=row["id"],
        email=row["email"],
        name=row["name"],
        role=row["role"],
        has_password=row["password_hash"] is not None,
        google_linked=row["google_sub"] is not None,
        email_verified=bool(row["email_verified"]),
        disabled=bool(row["disabled"]),
        default_model=row["default_model"],
        default_effort=row["default_effort"],
        created_at=row["created_at"],
        last_seen_at=row["last_seen_at"],
    )
