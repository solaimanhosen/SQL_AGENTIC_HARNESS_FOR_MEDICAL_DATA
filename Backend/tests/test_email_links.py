"""Links sent by email: resetting a password and confirming an address (ADR 0009)."""

import dataclasses
import re
import smtplib
import sqlite3
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from sql_agent import mailer as mailer_module
from sql_agent.accounts import AccountError, AccountStore
from sql_agent.appdb import MIGRATIONS, SCHEMA, SCHEMA_VERSION, AppDatabase
from sql_agent.auth import SignInThrottle
from sql_agent.config import ConfigError, load_settings
from sql_agent.google_login import GoogleIdentity, GoogleLoginError, resolve_account
from sql_agent.mailer import MailError, SmtpMailer, load_mailer
from sql_agent.passwords import PasswordRejected
from sql_agent.semantic import load_semantic_layer
from sql_agent.service import create_app

CSRF = {"X-Requested-With": "sql-agent"}
PASSWORD = "a long enough password"
NEW_PASSWORD = "another long password"
MAIL_SETTINGS = {
    "SQL_AGENT_SMTP_HOST": "smtp.example.org",
    "SQL_AGENT_SMTP_USERNAME": "sender@example.org",
    "SQL_AGENT_SMTP_PASSWORD": "app password",
    "SQL_AGENT_MAIL_FROM": "Patient data questions <sender@example.org>",
}


class Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.now


class FakeMailer:
    def __init__(self, fail: bool = False):
        self.sent: list[tuple[str, str, str]] = []
        self.fail = fail

    def send(self, to, subject, text):
        if self.fail:
            raise MailError("SMTPServerDisconnected: gone")
        self.sent.append((to, subject, text))

    def token(self, index: int = -1) -> str:
        return re.search(r"#token=([A-Za-z0-9_-]+)", self.sent[index][2]).group(1)


# The store -------------------------------------------------------------------------------


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def accounts(clock):
    return AccountStore(AppDatabase(), now=clock)


def test_a_reset_link_sets_the_password_once_and_ends_every_session(accounts):
    user = accounts.create_user("ann@example.org", password=PASSWORD)
    session = accounts.create_session(user.id)
    token = accounts.issue_email_token(user.id, "reset")
    after = accounts.use_reset_token(token, NEW_PASSWORD)
    assert after.email_verified, "opening the link proves the mailbox is theirs"
    assert accounts.authenticate("ann@example.org", NEW_PASSWORD) is not None
    assert accounts.resolve_session(session) is None
    with pytest.raises(AccountError) as refused:
        accounts.use_reset_token(token, "a third long password")
    assert refused.value.kind == "invalid_link"


def test_only_the_hash_of_a_link_is_stored(accounts):
    user = accounts.create_user("ann@example.org", password=PASSWORD)
    token = accounts.issue_email_token(user.id, "reset")
    stored = accounts.database.connection.execute("SELECT token_hash FROM email_tokens").fetchall()
    assert len(stored) == 1 and stored[0]["token_hash"] != token and token not in stored[0]["token_hash"]


def test_a_reset_link_expires_after_thirty_minutes(accounts, clock):
    user = accounts.create_user("ann@example.org", password=PASSWORD)
    token = accounts.issue_email_token(user.id, "reset")
    clock.now += timedelta(minutes=30)
    with pytest.raises(AccountError, match="expired"):
        accounts.use_reset_token(token, NEW_PASSWORD)
    assert accounts.authenticate("ann@example.org", PASSWORD) is not None


def test_a_confirmation_link_lasts_three_days(accounts, clock):
    user = accounts.create_user("ann@example.org", password=PASSWORD)
    token = accounts.issue_email_token(user.id, "verify")
    clock.now += timedelta(days=3) - timedelta(seconds=1)
    assert accounts.use_verify_token(token).email_verified


def test_a_newer_link_replaces_the_earlier_one(accounts):
    user = accounts.create_user("ann@example.org", password=PASSWORD)
    first = accounts.issue_email_token(user.id, "reset")
    second = accounts.issue_email_token(user.id, "reset")
    with pytest.raises(AccountError):
        accounts.use_reset_token(first, NEW_PASSWORD)
    accounts.use_reset_token(second, NEW_PASSWORD)


def test_a_link_works_only_for_its_own_purpose(accounts):
    user = accounts.create_user("ann@example.org", password=PASSWORD)
    verify = accounts.issue_email_token(user.id, "verify")
    with pytest.raises(AccountError):
        accounts.use_reset_token(verify, NEW_PASSWORD)
    assert accounts.authenticate("ann@example.org", PASSWORD) is not None
    assert accounts.use_verify_token(verify).email_verified, "the wrong use did not spend it"


def test_a_weak_password_keeps_the_link_for_another_try(accounts):
    user = accounts.create_user("ann@example.org", password=PASSWORD)
    token = accounts.issue_email_token(user.id, "reset")
    with pytest.raises(PasswordRejected):
        accounts.use_reset_token(token, "short")
    accounts.use_reset_token(token, NEW_PASSWORD)


def test_changing_the_password_any_other_way_voids_a_reset_link(accounts):
    user = accounts.create_user("ann@example.org", password=PASSWORD)
    token = accounts.issue_email_token(user.id, "reset")
    accounts.change_password(user.id, NEW_PASSWORD, current=PASSWORD)
    with pytest.raises(AccountError):
        accounts.use_reset_token(token, "a third long password")
    token = accounts.issue_email_token(user.id, "reset")
    accounts.reset_password(user.id, "an admin's temporary one")
    with pytest.raises(AccountError):
        accounts.use_reset_token(token, "a third long password")


def test_a_disabled_account_cannot_use_a_link(accounts):
    user = accounts.create_user("ann@example.org", password=PASSWORD)
    token = accounts.issue_email_token(user.id, "reset")
    accounts.set_disabled(user.id, True)
    with pytest.raises(AccountError):
        accounts.use_reset_token(token, NEW_PASSWORD)


def test_a_confirmed_self_registered_account_can_then_be_reached_by_google(accounts):
    ann = accounts.create_user("ann@example.org", password=PASSWORD)
    identity = GoogleIdentity(sub="google-ann", email="ann@example.org", name="Ann")
    with pytest.raises(GoogleLoginError):
        resolve_account(accounts, identity, link_user_id=None, registration_open=True)
    accounts.use_verify_token(accounts.issue_email_token(ann.id, "verify"))
    assert resolve_account(accounts, identity, link_user_id=None, registration_open=True).id == ann.id


def test_a_file_at_schema_version_5_gains_the_links_table(tmp_path):
    path = tmp_path / "conversations.db"
    old = sqlite3.connect(path)
    old.executescript(SCHEMA)
    for script in MIGRATIONS[:4]:
        old.executescript(script)
    old.execute("PRAGMA user_version = 5")
    old.execute(
        "INSERT INTO users (id, email, role, email_verified, created_at)"
        " VALUES ('u1', 'ann@example.org', 'admin', 1, '2026-10-21T12:00:00+00:00')"
    )
    old.commit()
    old.close()
    database = AppDatabase(path)
    assert database.schema_version() == SCHEMA_VERSION == 6
    accounts = AccountStore(database)
    assert accounts.get_user("u1").is_admin
    assert accounts.use_verify_token(accounts.issue_email_token("u1", "verify")).id == "u1"


# The routes ------------------------------------------------------------------------------


def _app(mailer, **kwargs):
    settings = dataclasses.replace(
        load_settings({}),
        conversations_path=None,
        request_log_path=None,
        secure_cookies=False,
        public_url="http://localhost:4200/",
    )
    agent = SimpleNamespace(settings=settings, db=None, layer=load_semantic_layer(), as_of=date(2026, 8, 16))
    return create_app(agent, google=None, mailer=mailer, **kwargs)


@pytest.fixture
def mail():
    return FakeMailer()


@pytest.fixture
def client(mail):
    return TestClient(_app(mail), headers=CSRF)


def _register(client, email="ann@example.org"):
    response = client.post("/api/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 201
    return response.json()


def test_the_sign_in_page_learns_whether_email_is_on(client):
    assert client.get("/api/auth/config").json()["email_enabled"] is True
    off = TestClient(_app(None), headers=CSRF)
    assert off.get("/api/auth/config").json()["email_enabled"] is False
    response = off.post("/api/auth/forgot", json={"email": "ann@example.org"})
    assert response.status_code == 503 and response.json()["error"] == "email_off"


def test_signing_up_sends_a_confirmation_link_and_confirming_needs_no_sign_in(client, mail):
    body = _register(client)
    assert body["email_verified"] is False
    (to, subject, text), = mail.sent
    assert to == "ann@example.org" and subject == "Confirm your email for Patient data questions"
    assert "http://localhost:4200/verify-email#token=" in text and "3 days" in text
    client.cookies.clear()
    assert client.post("/api/auth/verify", json={"token": mail.token()}).status_code == 204
    response = client.post("/api/auth/verify", json={"token": mail.token()})
    assert response.status_code == 400 and response.json()["error"] == "invalid_link"


def test_resetting_a_forgotten_password_end_to_end(client, mail):
    _register(client)
    client.cookies.clear()
    response = client.post("/api/auth/forgot", json={"email": "ANN@example.org"})
    assert response.status_code == 202 and response.json() == {"accepted": True}
    to, subject, text = mail.sent[-1]
    assert to == "ann@example.org" and subject == "Reset your password for Patient data questions"
    assert "http://localhost:4200/reset-password#token=" in text and "30 minutes" in text
    reset = client.post("/api/auth/reset", json={"token": mail.token(), "password": NEW_PASSWORD})
    assert reset.status_code == 204
    signed_in = client.post("/api/auth/login", json={"email": "ann@example.org", "password": NEW_PASSWORD})
    assert signed_in.status_code == 200 and signed_in.json()["email_verified"] is True


def test_a_reset_signs_out_the_browser_that_was_signed_in(client, mail):
    _register(client)
    client.post("/api/auth/forgot", json={"email": "ann@example.org"})
    client.post("/api/auth/reset", json={"token": mail.token(), "password": NEW_PASSWORD})
    assert client.get("/api/auth/me").status_code == 401


def test_asking_for_a_reset_does_not_say_whether_the_account_exists(client, mail):
    _register(client, "ann@example.org")
    before = len(mail.sent)
    known = client.post("/api/auth/forgot", json={"email": "ann@example.org"})
    unknown = client.post("/api/auth/forgot", json={"email": "nobody@example.org"})
    malformed = client.post("/api/auth/forgot", json={"email": "not an email"})
    assert known.status_code == unknown.status_code == malformed.status_code == 202
    assert known.json() == unknown.json() == malformed.json()
    assert [to for to, _, _ in mail.sent[before:]] == ["ann@example.org"]


def test_a_disabled_account_is_sent_nothing(client, mail):
    user = _register(client)
    client.app.state.accounts.set_disabled(user["id"], True)
    before = len(mail.sent)
    assert client.post("/api/auth/forgot", json={"email": "ann@example.org"}).status_code == 202
    assert len(mail.sent) == before


def test_asking_for_links_is_limited_per_email_with_its_own_message(mail):
    client = TestClient(_app(mail, email_throttle=SignInThrottle(per_address=10, per_email=2, message="Slow down.")))
    client.headers.update(CSRF)
    for _ in range(2):
        assert client.post("/api/auth/forgot", json={"email": "ann@example.org"}).status_code == 202
    response = client.post("/api/auth/forgot", json={"email": "ann@example.org"})
    assert response.status_code == 429 and response.json()["message"] == "Slow down."
    assert client.post("/api/auth/forgot", json={"email": "bo@example.org"}).status_code == 202


def test_a_signed_in_person_can_ask_for_the_confirmation_again(client, mail):
    _register(client)
    first = mail.token()
    assert client.post("/api/account/verify-email").status_code == 202
    assert mail.token() != first
    assert client.post("/api/auth/verify", json={"token": first}).status_code == 400, "the newer link replaced it"
    assert client.post("/api/auth/verify", json={"token": mail.token()}).status_code == 204
    assert client.get("/api/auth/me").json()["email_verified"] is True
    response = client.post("/api/account/verify-email")
    assert response.status_code == 409 and response.json()["error"] == "already_verified"


def test_asking_for_the_confirmation_needs_a_session(client):
    assert client.post("/api/account/verify-email").status_code == 401


def test_a_mail_server_failure_is_logged_and_the_answer_is_unchanged(caplog):
    client = TestClient(_app(FakeMailer(fail=True)), headers=CSRF)
    assert client.post("/api/auth/register", json={"email": "ann@example.org", "password": PASSWORD}).status_code == 201
    response = client.post("/api/auth/forgot", json={"email": "ann@example.org"})
    assert response.status_code == 202
    assert "Could not send the reset email" in caplog.text and "token=" not in caplog.text


def test_the_overview_shows_whether_email_is_on(client):
    accounts = client.app.state.accounts
    accounts.create_user("admin@example.org", password=PASSWORD, role="admin", email_verified=True)
    client.post("/api/auth/login", json={"email": "admin@example.org", "password": PASSWORD})
    assert client.get("/api/admin/overview").json()["email_enabled"] is True


# The mailer ------------------------------------------------------------------------------


def test_email_is_off_until_every_required_setting_is_there():
    assert load_mailer({}) is None
    for missing in MAIL_SETTINGS:
        assert load_mailer({key: value for key, value in MAIL_SETTINGS.items() if key != missing}) is None
    mailer = load_mailer(MAIL_SETTINGS)
    assert (mailer.host, mailer.port, mailer.username) == ("smtp.example.org", 587, "sender@example.org")
    assert "app password" not in repr(mailer)
    assert load_mailer({**MAIL_SETTINGS, "SQL_AGENT_SMTP_PORT": "465"}).port == 465


@pytest.mark.parametrize(
    "settings",
    [{"SQL_AGENT_SMTP_PORT": "smtp"}, {"SQL_AGENT_SMTP_PORT": "70000"}, {"SQL_AGENT_MAIL_FROM": "nobody"}],
)
def test_a_malformed_mail_setting_is_refused(settings):
    with pytest.raises(ConfigError):
        load_mailer({**MAIL_SETTINGS, **settings})


class StubSmtp:
    """Records what smtplib would have done."""

    instances: list = []

    def __init__(self, host, port, timeout=None, context=None):
        self.calls = [("connect", host, port, timeout)]
        StubSmtp.instances.append(self)

    def starttls(self, context=None):
        self.calls.append(("starttls",))

    def login(self, username, password):
        self.calls.append(("login", username, password))

    def send_message(self, message):
        self.calls.append(("send", message["To"], message["From"], message["Subject"], message.get_content()))

    def close(self):
        self.calls.append(("close",))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.calls.append(("quit",))


@pytest.fixture
def stub_smtp(monkeypatch):
    StubSmtp.instances = []
    monkeypatch.setattr(mailer_module.smtplib, "SMTP", StubSmtp)
    monkeypatch.setattr(mailer_module.smtplib, "SMTP_SSL", StubSmtp)
    return StubSmtp


def test_a_message_goes_out_over_starttls_after_signing_in(stub_smtp):
    load_mailer(MAIL_SETTINGS).send("ann@example.org", "Hello", "Body text\n")
    (smtp,) = stub_smtp.instances
    assert [call[0] for call in smtp.calls] == ["connect", "starttls", "login", "send", "quit"]
    assert smtp.calls[0] == ("connect", "smtp.example.org", 587, mailer_module.TIMEOUT_SECONDS)
    assert smtp.calls[3][1:4] == ("ann@example.org", "Patient data questions <sender@example.org>", "Hello")


def test_port_465_uses_tls_from_the_start(stub_smtp):
    load_mailer({**MAIL_SETTINGS, "SQL_AGENT_SMTP_PORT": "465"}).send("ann@example.org", "Hello", "Body\n")
    assert [call[0] for call in stub_smtp.instances[0].calls] == ["connect", "login", "send", "quit"]


def test_a_refused_sign_in_becomes_a_mail_error_and_closes_the_connection(monkeypatch, stub_smtp):
    def refuse(self, username, password):
        raise smtplib.SMTPAuthenticationError(535, b"Username and Password not accepted")

    monkeypatch.setattr(StubSmtp, "login", refuse)
    with pytest.raises(MailError, match="SMTPAuthenticationError"):
        SmtpMailer("smtp.example.org", 587, "sender@example.org", "app password", "sender@example.org").check()
    assert stub_smtp.instances[0].calls[-1] == ("close",)


def test_the_test_command_sends_one_message(monkeypatch, stub_smtp, capsys):
    for key, value in MAIL_SETTINGS.items():
        monkeypatch.setenv(key, value)
    assert mailer_module.main(["ann@example.org"]) == 0
    assert stub_smtp.instances[0].calls[3][1] == "ann@example.org"
    assert "app password" not in capsys.readouterr().out


def test_the_test_command_explains_when_email_is_off(capsys):
    assert mailer_module.main(["ann@example.org"]) == 1
    assert "Email is off" in capsys.readouterr().err
