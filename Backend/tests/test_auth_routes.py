"""Signing up, in and out over HTTP, and a person's own account settings."""

import dataclasses
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from sql_agent.auth import SignInThrottle
from sql_agent.config import load_settings
from sql_agent.db import ReadOnlyDatabase
from sql_agent.semantic import load_semantic_layer
from sql_agent.service import create_app

CSRF = {"X-Requested-With": "sql-agent"}
PASSWORD = "a long enough password"


@pytest.fixture
def app(sample_db_path, tmp_path):
    settings = dataclasses.replace(
        load_settings({}),
        db_path=sample_db_path,
        log_path=None,
        request_log_path=None,
        conversations_path=None,
        secure_cookies=False,
    )
    agent = SimpleNamespace(
        settings=settings,
        db=ReadOnlyDatabase(sample_db_path, max_rows=10, timeout_seconds=5),
        layer=load_semantic_layer(),
        as_of=date(2026, 8, 16),
    )
    return create_app(agent, google=None, mailer=None, throttle=SignInThrottle(per_address=5, per_email=3))


@pytest.fixture
def client(app):
    return TestClient(app, headers=CSRF)


def _register(client, email="ann@example.org", password=PASSWORD, name="Ann"):
    return client.post("/api/auth/register", json={"email": email, "password": password, "name": name})


def test_registering_signs_you_in_as_a_user_with_a_safe_cookie(client):
    response = _register(client)
    assert response.status_code == 201
    body = response.json()
    assert (body["email"], body["name"], body["role"], body["has_password"]) == ("ann@example.org", "Ann", "user", True)
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/api" in cookie
    assert client.get("/api/auth/me").json()["email"] == "ann@example.org"


@pytest.mark.parametrize(
    "body,status,error",
    [
        ({"email": "ann@example.org", "password": "short"}, 422, "weak_password"),
        ({"email": "not-an-email", "password": PASSWORD}, 422, "invalid_email"),
        ({"email": "ann@example.org"}, 422, "invalid_request"),
    ],
)
def test_a_bad_registration_says_what_is_wrong(client, body, status, error):
    response = client.post("/api/auth/register", json=body)
    assert response.status_code == status and response.json()["error"] == error


def test_an_email_can_be_registered_once(client):
    assert _register(client).status_code == 201
    again = _register(TestClient(client.app, headers=CSRF), email="ANN@example.org")
    assert again.status_code == 409 and again.json()["error"] == "email_taken"


def test_closed_registration_refuses_new_accounts_but_not_sign_in(client):
    _register(client)
    client.app.state.accounts.set_registration(False)
    stranger = TestClient(client.app, headers=CSRF)
    assert stranger.get("/api/auth/config").json()["registration_open"] is False
    refused = _register(stranger, email="bo@example.org")
    assert refused.status_code == 403 and refused.json()["error"] == "registration_closed"
    assert stranger.post("/api/auth/login", json={"email": "ann@example.org", "password": PASSWORD}).status_code == 200


def test_a_wrong_password_and_an_unknown_email_get_the_same_answer(client):
    _register(client)
    fresh = TestClient(client.app, headers=CSRF)
    wrong = fresh.post("/api/auth/login", json={"email": "ann@example.org", "password": "not the password"})
    unknown = fresh.post("/api/auth/login", json={"email": "nobody@example.org", "password": "not the password"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {
        "error": "invalid_credentials",
        "message": "The email or password is not correct.",
    }
    assert "set-cookie" not in wrong.headers


def test_repeated_failures_are_throttled_and_say_nothing_about_the_account(client):
    _register(client)
    fresh = TestClient(client.app, headers=CSRF)
    for _ in range(3):
        fresh.post("/api/auth/login", json={"email": "ann@example.org", "password": "not the password"})
    blocked = fresh.post("/api/auth/login", json={"email": "ann@example.org", "password": PASSWORD})
    assert blocked.status_code == 429 and blocked.json()["error"] == "too_many_attempts"
    assert blocked.headers["retry-after"] == "600"


def test_signing_out_ends_the_session_on_the_service_too(client):
    _register(client)
    token = client.cookies.get("sql_agent_session")
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401
    replay = TestClient(client.app, headers=CSRF)
    replay.cookies.set("sql_agent_session", token)
    assert replay.get("/api/auth/me").status_code == 401, "a copied cookie is dead after sign-out"


def test_a_disabled_account_is_signed_out_at_once(client):
    user = _register(client).json()
    client.app.state.accounts.set_disabled(user["id"], True)
    assert client.get("/api/auth/me").status_code == 401
    retry = client.post("/api/auth/login", json={"email": "ann@example.org", "password": PASSWORD})
    assert retry.status_code == 401


def test_the_name_and_default_model_can_be_changed_but_only_to_models_on_offer(client):
    _register(client)
    updated = client.patch("/api/account", json={"name": "Ann Lee", "default_model": "claude-haiku-5-5"})
    assert updated.status_code == 200
    assert (updated.json()["name"], updated.json()["default_model"]) == ("Ann Lee", "claude-haiku-5-5")
    assert client.get("/api/models").json()["default_model"] == "claude-haiku-5-5"
    for body in ({"default_model": "claude-fable-5-1"}, {"default_model": "gpt-5"}, {"default_effort": "low"}):
        assert client.patch("/api/account", json=body).status_code == 422
    cleared = client.patch("/api/account", json={"default_model": None})
    assert cleared.json()["default_model"] is None


def test_a_password_change_needs_the_current_password(client):
    _register(client)
    wrong = client.post("/api/account/password", json={"current": "nope", "new": "a brand new password"})
    assert wrong.status_code == 403 and wrong.json()["error"] == "wrong_password"
    assert client.post("/api/account/password", json={"current": PASSWORD, "new": "short"}).status_code == 422
    assert client.post("/api/account/password", json={"current": PASSWORD, "new": "a brand new password"}).status_code == 204
    fresh = TestClient(client.app, headers=CSRF)
    assert fresh.post("/api/auth/login", json={"email": "ann@example.org", "password": "a brand new password"}).status_code == 200


def test_sessions_are_listed_and_others_can_be_signed_out(client):
    _register(client)
    laptop = TestClient(client.app, headers=CSRF)
    laptop.post("/api/auth/login", json={"email": "ann@example.org", "password": PASSWORD})
    sessions = client.get("/api/account/sessions").json()
    assert len(sessions) == 2 and sum(item["current"] for item in sessions) == 1
    assert client.post("/api/account/sessions/revoke-others").json() == {"revoked": 1}
    assert laptop.get("/api/auth/me").status_code == 401 and client.get("/api/auth/me").status_code == 200
    assert client.delete("/api/account/sessions/0000").status_code == 404


def test_with_secure_cookies_on_the_session_cookie_is_https_only():
    settings = dataclasses.replace(load_settings({}), conversations_path=None, request_log_path=None, secure_cookies=True)
    secure_app = create_app(
        SimpleNamespace(settings=settings, db=None, layer=load_semantic_layer(), as_of=date(2026, 8, 16)),
        google=None,
        mailer=None,
    )
    response = _register(TestClient(secure_app, headers=CSRF))
    assert "secure" in response.headers["set-cookie"].lower()
