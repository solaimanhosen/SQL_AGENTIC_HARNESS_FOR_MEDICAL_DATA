"""The HTTP routes for accounts: signing up and in, Google sign-in, and a person's own settings.

They sit beside the routes in service.py, which build them with the same stores. Errors use
the service's usual body, `{error, message}`. Sign-in failures never say whether the email
exists, and Google failures reach the login page as a short code only.
"""

from __future__ import annotations

import secrets
from dataclasses import asdict

import anyio
from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from .accounts import MAX_EMAIL_CHARS, MAX_NAME_CHARS, AccountError, AccountStore, User
from .auth import SESSION_COOKIE, Sessions, SignInThrottle, clear_session_cookie, set_session_cookie
from .config import Settings
from .google_login import (
    STATE_COOKIE,
    STATE_COOKIE_PATH,
    GoogleConfig,
    GoogleLoginError,
    TokenExchange,
    begin,
    identity_from,
    resolve_account,
    safe_next,
)
from .models import ModelChoiceError, resolve_choice
from .passwords import MAX_PASSWORD_CHARS


class UserOut(BaseModel):
    id: str
    email: str
    name: str
    role: str
    has_password: bool
    google_linked: bool
    default_model: str | None
    default_effort: str | None


class AuthConfigOut(BaseModel):
    registration_open: bool
    google_enabled: bool


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=MAX_EMAIL_CHARS)
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_CHARS)
    name: str = Field(default="", max_length=MAX_NAME_CHARS)


class LoginRequest(BaseModel):
    email: str = Field(min_length=1, max_length=MAX_EMAIL_CHARS)
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_CHARS)


class AccountUpdate(BaseModel):
    """Fields left out are not changed. `default_model: null` clears the default."""

    name: str | None = Field(default=None, max_length=MAX_NAME_CHARS)
    default_model: str | None = Field(default=None, max_length=64)
    default_effort: str | None = Field(default=None, max_length=16)


class PasswordChange(BaseModel):
    current: str | None = Field(default=None, max_length=MAX_PASSWORD_CHARS)
    new: str = Field(min_length=1, max_length=MAX_PASSWORD_CHARS)


class SessionOut(BaseModel):
    id: str
    created_at: str
    last_used_at: str
    expires_at: str
    user_agent: str
    current: bool


class InvalidCredentials(Exception):
    """The email and password do not match an enabled account."""


def user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        name=user.name,
        role=user.role,
        has_password=user.has_password,
        google_linked=user.google_linked,
        default_model=user.default_model,
        default_effort=user.default_effort,
    )


def account_router(
    *,
    accounts: AccountStore,
    sessions: Sessions,
    settings: Settings,
    google: GoogleConfig | None,
    token_exchange: TokenExchange,
    throttle: SignInThrottle,
) -> APIRouter:
    router = APIRouter()
    secure = settings.secure_cookies

    def registration_open() -> bool:
        return accounts.registration_open(default=settings.registration_open)

    def signed_in(response: Response, user: User, request: Request) -> UserOut:
        token = accounts.create_session(user.id, user_agent=request.headers.get("user-agent", ""))
        set_session_cookie(response, token, secure=secure)
        request.state.user_id = user.id
        return user_out(user)

    @router.get("/api/auth/config")
    def auth_config() -> AuthConfigOut:
        """What the sign-in page should offer."""
        return AuthConfigOut(registration_open=registration_open(), google_enabled=google is not None)

    @router.post("/api/auth/register", status_code=201)
    def register(body: RegisterRequest, request: Request, response: Response) -> UserOut:
        if not registration_open():
            raise AccountError("registration_closed", "New accounts are not being accepted.")
        user = accounts.create_user(body.email, password=body.password, name=body.name)
        return signed_in(response, user, request)

    @router.post("/api/auth/login")
    def login(body: LoginRequest, request: Request, response: Response) -> UserOut:
        address = request.client.host if request.client else "unknown"
        throttle.check(address, body.email)
        user = accounts.authenticate(body.email, body.password)
        if user is None:
            throttle.failed(address, body.email)
            raise InvalidCredentials()
        throttle.succeeded(body.email)
        return signed_in(response, user, request)

    @router.post("/api/auth/logout", status_code=204)
    def logout(request: Request, _: User = Depends(sessions.current)) -> Response:
        accounts.end_session(request.cookies.get(SESSION_COOKIE, ""))
        response = Response(status_code=204)
        clear_session_cookie(response, secure=secure)
        return response

    @router.get("/api/auth/me")
    def me(user: User = Depends(sessions.current)) -> UserOut:
        return user_out(user)

    @router.patch("/api/account")
    def update_account(body: AccountUpdate, user: User = Depends(sessions.current)) -> UserOut:
        changes = body.model_dump(exclude_unset=True)
        model = changes.get("default_model")
        effort = changes.get("default_effort")
        if model is not None:
            option, effort = resolve_choice(
                model, effort, default_model=settings.model, default_effort=settings.effort, admin=user.is_admin
            )
            model = option.id
        elif effort is not None and "default_model" not in changes:
            raise ModelChoiceError("Choose a default model to go with the effort.")
        updated = accounts.update_profile(
            user.id,
            name=changes.get("name"),
            default_model=model,
            default_effort=effort,
            clear_default_model="default_model" in changes and model is None,
        )
        return user_out(updated)

    @router.post("/api/account/password", status_code=204)
    def change_password(body: PasswordChange, user: User = Depends(sessions.current)) -> Response:
        accounts.change_password(user.id, body.new, current=body.current)
        return Response(status_code=204)

    @router.get("/api/account/sessions")
    def list_sessions(request: Request, user: User = Depends(sessions.current)) -> list[SessionOut]:
        current = request.state.session_id
        return [
            SessionOut(**asdict(info), current=info.id == current) for info in accounts.list_sessions(user.id)
        ]

    @router.delete("/api/account/sessions/{session_id}", status_code=204)
    def revoke_session(session_id: str, user: User = Depends(sessions.current)) -> Response:
        if not accounts.revoke_session(user.id, session_id):
            raise AccountError("unknown_session", "No such session.")
        return Response(status_code=204)

    @router.post("/api/account/sessions/revoke-others")
    def revoke_others(request: Request, user: User = Depends(sessions.current)) -> dict:
        return {"revoked": accounts.revoke_other_sessions(user.id, request.state.session_id)}

    @router.post("/api/account/google/disconnect")
    def disconnect_google(user: User = Depends(sessions.current)) -> UserOut:
        return user_out(accounts.unlink_google(user.id))

    @router.get("/api/auth/google/start", response_class=RedirectResponse, status_code=302)
    def google_start(
        request: Request,
        next: str = Query(default="/", max_length=500),  # noqa: A002  (the parameter's public name)
        link: bool = False,
    ) -> RedirectResponse:
        """Send the browser to Google. With `link=true`, connect Google to the signed-in account."""
        if google is None:
            return RedirectResponse("/login?error=google_off", status_code=302)
        link_user_id = None
        if link:
            resolved = accounts.resolve_session(request.cookies.get(SESSION_COOKIE))
            if resolved is None:
                return RedirectResponse("/login?error=signed_out", status_code=302)
            link_user_id = resolved[0].id
        state, url = begin(accounts, google, next_path=next, link_user_id=link_user_id)
        response = RedirectResponse(url, status_code=302)
        # Lax, not Strict: Google's redirect back is a top-level navigation from another site.
        response.set_cookie(
            STATE_COOKIE, state, max_age=600, path=STATE_COOKIE_PATH, httponly=True, secure=secure, samesite="lax"
        )
        return response

    @router.get("/api/auth/google/callback", response_class=RedirectResponse, status_code=302)
    async def google_callback(
        request: Request,
        code: str | None = Query(default=None, max_length=2000),
        state: str | None = Query(default=None, max_length=200),
        error: str | None = Query(default=None, max_length=200),
    ) -> RedirectResponse:
        """Where Google returns the browser. Signs in, or goes to the login page with a code."""
        failure_page = "/login"
        try:
            if google is None:
                raise GoogleLoginError("google_off")
            if error is not None:
                raise GoogleLoginError("google_cancelled", error)
            expected = request.cookies.get(STATE_COOKIE, "")
            if not code or not state or not expected or not secrets.compare_digest(state, expected):
                raise GoogleLoginError("state_mismatch")
            pending = accounts.take_oauth_state(state)
            if pending is None:
                raise GoogleLoginError("expired")
            if pending.link_user_id is not None:
                failure_page = "/account"
            tokens = await anyio.to_thread.run_sync(token_exchange, google, code, pending.code_verifier)
            identity = identity_from(tokens, google, nonce=pending.nonce)
            user = resolve_account(
                accounts, identity, link_user_id=pending.link_user_id, registration_open=registration_open()
            )
        except GoogleLoginError as exc:
            request.state.refused = f"google:{exc.code}"
            response = RedirectResponse(f"{failure_page}?error={exc.code}", status_code=302)
        else:
            response = RedirectResponse(safe_next(pending.next_path), status_code=302)
            if pending.link_user_id is None:
                signed_in(response, user, request)
        response.delete_cookie(STATE_COOKIE, path=STATE_COOKIE_PATH, httponly=True, secure=secure, samesite="lax")
        return response

    return router

