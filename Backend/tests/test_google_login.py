"""Google sign-in, with Google's token endpoint replaced by a fake. No network is used."""

import base64
import dataclasses
import json
import time
from datetime import date
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from sql_agent.accounts import AccountStore
from sql_agent.appdb import AppDatabase
from sql_agent.config import load_settings
from sql_agent.google_login import (
    GoogleConfig,
    GoogleIdentity,
    GoogleLoginError,
    identity_from,
    load_google_config,
    resolve_account,
    safe_next,
)
from sql_agent.semantic import load_semantic_layer
from sql_agent.service import create_app

CONFIG = GoogleConfig("client-123", "secret-456", "http://localhost:4200/api/auth/google/callback")
CSRF = {"X-Requested-With": "sql-agent"}


def id_token(**claims) -> str:
    """An ID token shaped like Google's. Its signature is not read, as explained in google_login."""
    body = {
        "iss": "https://accounts.google.com",
        "aud": CONFIG.client_id,
        "exp": time.time() + 600,
        "sub": "google-1",
        "email": "ann@gmail.com",
        "email_verified": True,
        "name": "Ann Lee",
    } | claims
    encode = lambda part: base64.urlsafe_b64encode(json.dumps(part).encode()).rstrip(b"=").decode()  # noqa: E731
    return f"{encode({'alg': 'RS256'})}.{encode(body)}.signature"


# Reading the claims --------------------------------------------------------------------


def test_the_claims_of_a_good_token_name_the_person():
    identity = identity_from({"id_token": id_token(nonce="n1")}, CONFIG, nonce="n1")
    assert identity == GoogleIdentity(sub="google-1", email="ann@gmail.com", name="Ann Lee")


@pytest.mark.parametrize(
    "claims,code",
    [
        ({"iss": "https://evil.example"}, "invalid_token"),
        ({"aud": "someone-else"}, "invalid_token"),
        ({"exp": time.time() - 1}, "invalid_token"),
        ({"nonce": "replayed"}, "invalid_token"),
        ({"sub": ""}, "invalid_token"),
        ({"email_verified": False}, "email_unverified"),
        ({"email_verified": "true"}, "email_unverified"),
    ],
)
def test_a_token_that_fails_any_check_is_refused(claims, code):
    tokens = {"id_token": id_token(**({"nonce": "n1"} | claims))}
    with pytest.raises(GoogleLoginError) as refused:
        identity_from(tokens, CONFIG, nonce="n1")
    assert refused.value.code == code


@pytest.mark.parametrize("tokens", [{}, {"id_token": "not-a-jwt"}, {"id_token": "a.!!!.c"}])
def test_an_unreadable_token_is_refused(tokens):
    with pytest.raises(GoogleLoginError, match="no readable ID token"):
        identity_from(tokens, CONFIG, nonce="n1")


@pytest.mark.parametrize(
    "path,expected",
    [
        ("/c/" + "a" * 32, "/c/" + "a" * 32),
        ("/account?tab=security", "/account?tab=security"),
        (None, "/"),
        ("https://evil.example", "/"),
        ("//evil.example", "/"),
        ("/\\evil.example", "/"),
        ("/api/auth/logout", "/"),
        ("/\nSet-Cookie:x", "/"),
    ],
)
def test_only_a_path_inside_the_application_is_returned_to(path, expected):
    assert safe_next(path) == expected


def test_google_is_off_until_both_its_id_and_secret_are_set():
    assert load_google_config("http://localhost:4200", {}) is None
    assert load_google_config("http://localhost:4200", {"SQL_AGENT_GOOGLE_CLIENT_ID": "x"}) is None
    config = load_google_config(
        "https://agent.example.org/", {"SQL_AGENT_GOOGLE_CLIENT_ID": "x", "SQL_AGENT_GOOGLE_CLIENT_SECRET": "y"}
    )
    assert config.redirect_uri == "https://agent.example.org/api/auth/google/callback"


# Which account a Google sign-in reaches -----------------------------------------------------


@pytest.fixture
def accounts():
    return AccountStore(AppDatabase())


IDENTITY = GoogleIdentity(sub="google-1", email="ann@gmail.com", name="Ann Lee")


def test_a_new_person_gets_a_google_account_with_a_verified_email(accounts):
    user = resolve_account(accounts, IDENTITY, link_user_id=None, registration_open=True)
    assert (user.email, user.name, user.google_linked, user.has_password, user.email_verified) == (
        "ann@gmail.com",
        "Ann Lee",
        True,
        False,
        True,
    )
    assert resolve_account(accounts, IDENTITY, link_user_id=None, registration_open=False).id == user.id


def test_closed_registration_turns_a_new_person_away(accounts):
    with pytest.raises(GoogleLoginError) as refused:
        resolve_account(accounts, IDENTITY, link_user_id=None, registration_open=False)
    assert refused.value.code == "registration_closed"


def test_an_account_an_admin_created_is_linked_by_its_email(accounts):
    admin = accounts.create_user("ann@gmail.com", password="a long enough password", role="admin", email_verified=True)
    user = resolve_account(accounts, IDENTITY, link_user_id=None, registration_open=False)
    assert user.id == admin.id and user.google_linked and user.is_admin


def test_a_self_registered_account_is_never_linked_by_email(accounts):
    # Someone registered this address with a password; nobody checked it was theirs.
    squatter = accounts.create_user("ann@gmail.com", password="a long enough password")
    with pytest.raises(GoogleLoginError) as refused:
        resolve_account(accounts, IDENTITY, link_user_id=None, registration_open=True)
    assert refused.value.code == "link_required"
    assert not accounts.get_user(squatter.id).google_linked


def test_a_signed_in_person_can_connect_google_whatever_its_email(accounts):
    ann = accounts.create_user("ann@work.example", password="a long enough password")
    user = resolve_account(accounts, IDENTITY, link_user_id=ann.id, registration_open=False)
    assert user.id == ann.id and user.google_linked
    other = accounts.create_user("bo@work.example", password="a long enough password")
    with pytest.raises(GoogleLoginError) as refused:
        resolve_account(accounts, IDENTITY, link_user_id=other.id, registration_open=True)
    assert refused.value.code == "google_in_use"


def test_a_disabled_account_cannot_sign_in_with_google(accounts):
    user = resolve_account(accounts, IDENTITY, link_user_id=None, registration_open=True)
    accounts.set_disabled(user.id, True)
    with pytest.raises(GoogleLoginError) as refused:
        resolve_account(accounts, IDENTITY, link_user_id=None, registration_open=True)
    assert refused.value.code == "disabled"


# The whole round trip over HTTP --------------------------------------------------------------


class FakeGoogle:
    """Stands in for Google's token endpoint, issuing a token for the last authorization."""

    def __init__(self, **claims):
        self.claims = claims
        self.exchanges = []
        self.nonce = None

    def authorize(self, location: str) -> str:
        """Follow the redirect to Google: remember the nonce, and return the state Google echoes."""
        query = parse_qs(urlparse(location).query)
        assert query["code_challenge_method"] == ["S256"] and query["scope"] == ["openid email profile"]
        self.nonce = query["nonce"][0]
        return query["state"][0]

    def __call__(self, config, code, verifier):
        self.exchanges.append((code, verifier))
        return {"id_token": id_token(nonce=self.nonce, **self.claims)}


@pytest.fixture
def google_app(sample_db_path):
    settings = dataclasses.replace(load_settings({}), conversations_path=None, request_log_path=None, secure_cookies=False)
    fake = FakeGoogle()
    agent = SimpleNamespace(settings=settings, db=None, layer=load_semantic_layer(), as_of=date(2026, 8, 16))
    app = create_app(agent, google=CONFIG, token_exchange=fake)
    return app, fake


def _start(client, **params):
    response = client.get("/api/auth/google/start", params=params, follow_redirects=False)
    assert response.status_code == 302
    return response


def test_signing_in_with_google_end_to_end(google_app):
    app, fake = google_app
    client = TestClient(app, headers=CSRF)
    assert client.get("/api/auth/config").json()["google_enabled"] is True
    started = _start(client, next="/c/" + "a" * 32)
    assert started.headers["location"].startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "samesite=lax" in started.headers["set-cookie"].lower()
    state = fake.authorize(started.headers["location"])

    back = client.get("/api/auth/google/callback", params={"code": "c1", "state": state}, follow_redirects=False)
    assert back.status_code == 302 and back.headers["location"] == "/c/" + "a" * 32
    assert client.get("/api/auth/me").json()["email"] == "ann@gmail.com"
    code, verifier = fake.exchanges[0]
    assert code == "c1" and len(verifier) >= 43, "the PKCE verifier went to Google, never to the browser"


def test_a_callback_is_refused_without_the_browser_s_own_state(google_app):
    app, fake = google_app
    victim = TestClient(app, headers=CSRF)
    attacker = TestClient(app, headers=CSRF)
    state = fake.authorize(_start(attacker).headers["location"])
    # The attacker's callback link opened in the victim's browser, which has no state cookie.
    back = victim.get("/api/auth/google/callback", params={"code": "c1", "state": state}, follow_redirects=False)
    assert back.headers["location"] == "/login?error=state_mismatch"
    assert victim.get("/api/auth/me").status_code == 401 and fake.exchanges == []


def test_a_state_works_once(google_app):
    app, fake = google_app
    client = TestClient(app, headers=CSRF)
    state = fake.authorize(_start(client).headers["location"])
    cookie = client.cookies.get("sql_agent_oauth")
    client.get("/api/auth/google/callback", params={"code": "c1", "state": state}, follow_redirects=False)
    replay = TestClient(app, headers=CSRF)
    replay.cookies.set("sql_agent_oauth", cookie)
    again = replay.get("/api/auth/google/callback", params={"code": "c1", "state": state}, follow_redirects=False)
    assert again.headers["location"] == "/login?error=expired"


def test_cancelling_at_google_returns_to_the_login_page(google_app):
    app, _ = google_app
    client = TestClient(app, headers=CSRF)
    _start(client)
    back = client.get("/api/auth/google/callback", params={"error": "access_denied"}, follow_redirects=False)
    assert back.headers["location"] == "/login?error=google_cancelled"


def test_connecting_google_from_a_signed_in_account(google_app):
    app, fake = google_app
    client = TestClient(app, headers=CSRF)
    client.post("/api/auth/register", json={"email": "ann@work.example", "password": "a long enough password"})
    state = fake.authorize(_start(client, link="true", next="/account").headers["location"])
    back = client.get("/api/auth/google/callback", params={"code": "c1", "state": state}, follow_redirects=False)
    assert back.headers["location"] == "/account"
    me = client.get("/api/auth/me").json()
    assert me["email"] == "ann@work.example" and me["google_linked"] is True


def test_google_sign_in_is_off_without_credentials(sample_db_path):
    settings = dataclasses.replace(load_settings({}), conversations_path=None, request_log_path=None, secure_cookies=False)
    agent = SimpleNamespace(settings=settings, db=None, layer=load_semantic_layer(), as_of=date(2026, 8, 16))
    client = TestClient(create_app(agent, google=None), headers=CSRF)
    assert client.get("/api/auth/config").json()["google_enabled"] is False
    assert _start(client).headers["location"] == "/login?error=google_off"


def test_a_failed_connection_returns_to_the_security_settings_with_a_code(google_app):
    app, fake = google_app
    owner = TestClient(app, headers=CSRF)
    state = fake.authorize(_start(owner).headers["location"])
    owner.get("/api/auth/google/callback", params={"code": "c1", "state": state}, follow_redirects=False)

    other = TestClient(app, headers=CSRF)
    other.post("/api/auth/register", json={"email": "bo@work.example", "password": "a long enough password"})
    state = fake.authorize(_start(other, link="true", next="/account").headers["location"])
    back = other.get("/api/auth/google/callback", params={"code": "c2", "state": state}, follow_redirects=False)
    assert back.headers["location"] == "/account?tab=security&error=google_in_use"
    assert other.get("/api/auth/me").json()["google_linked"] is False
