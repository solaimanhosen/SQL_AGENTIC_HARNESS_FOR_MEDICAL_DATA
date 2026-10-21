from datetime import datetime, timedelta, timezone

import pytest

from sql_agent.accounts import AccountError, AccountStore
from sql_agent.appdb import AppDatabase
from sql_agent.passwords import PasswordRejected

PASSWORD = "a long enough password"


class Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def accounts(clock):
    return AccountStore(AppDatabase(), now=clock)


def test_an_account_is_found_by_email_whatever_its_case(accounts):
    user = accounts.create_user("  Ann@Example.ORG ", password=PASSWORD, name=" Ann ")
    assert (user.email, user.name, user.role) == ("ann@example.org", "Ann", "user")
    assert user.has_password and not user.google_linked and not user.email_verified
    assert accounts.find_by_email("ANN@example.org").id == user.id
    with pytest.raises(AccountError, match="already exists"):
        accounts.create_user("ann@EXAMPLE.org", password=PASSWORD)


@pytest.mark.parametrize("email", ["", "ann", "ann@", "@example.org", "ann @example.org", "a" * 250 + "@x.org"])
def test_a_malformed_email_is_refused(accounts, email):
    with pytest.raises(AccountError) as refused:
        accounts.create_user(email, password=PASSWORD)
    assert refused.value.kind == "invalid_email"


def test_a_weak_password_is_refused_before_anything_is_stored(accounts):
    with pytest.raises(PasswordRejected):
        accounts.create_user("ann@example.org", password="short")
    assert accounts.list_users() == []


def test_sign_in_needs_the_right_password_on_an_enabled_account(accounts):
    user = accounts.create_user("ann@example.org", password=PASSWORD)
    assert accounts.authenticate("ANN@example.org", PASSWORD).id == user.id
    assert accounts.authenticate("ann@example.org", PASSWORD + "!") is None
    assert accounts.authenticate("nobody@example.org", PASSWORD) is None
    assert accounts.authenticate("not an email", PASSWORD) is None
    accounts.set_disabled(user.id, True)
    assert accounts.authenticate("ann@example.org", PASSWORD) is None


def test_a_google_only_account_cannot_sign_in_with_a_password(accounts):
    accounts.create_user("ann@example.org", google_sub="g-1", email_verified=True)
    assert accounts.authenticate("ann@example.org", "") is None
    assert accounts.authenticate("ann@example.org", PASSWORD) is None


def test_a_session_resolves_until_it_is_ended_and_only_its_hash_is_stored(accounts):
    user = accounts.create_user("ann@example.org", password=PASSWORD)
    token = accounts.create_session(user.id, user_agent="Firefox")
    found, session_id = accounts.resolve_session(token)
    assert found.id == user.id
    stored = accounts.database.connection.execute("SELECT token_hash FROM sessions").fetchone()[0]
    assert token not in stored and len(stored) == 64
    assert accounts.resolve_session(token + "x") is None
    assert accounts.resolve_session(None) is None
    accounts.end_session(token)
    assert accounts.resolve_session(token) is None


def test_a_session_ends_after_30_idle_days_or_90_days_in_all(accounts, clock):
    user = accounts.create_user("ann@example.org", password=PASSWORD)
    idle = accounts.create_session(user.id)
    clock.now += timedelta(days=30)
    assert accounts.resolve_session(idle) is None

    busy = accounts.create_session(user.id)
    for _ in range(8):
        clock.now += timedelta(days=10)
        assert accounts.resolve_session(busy) is not None, "use keeps it alive"
    clock.now += timedelta(days=10)
    assert accounts.resolve_session(busy) is None, "but never past 90 days"


def test_disabling_an_account_ends_its_sessions(accounts):
    user = accounts.create_user("ann@example.org", password=PASSWORD)
    token = accounts.create_session(user.id)
    accounts.set_disabled(user.id, True)
    assert accounts.resolve_session(token) is None
    accounts.set_disabled(user.id, False)
    assert accounts.resolve_session(token) is None, "a re-enabled account signs in again"


def test_sessions_can_be_listed_and_revoked_by_their_owner_only(accounts):
    ann = accounts.create_user("ann@example.org", password=PASSWORD)
    bo = accounts.create_user("bo@example.org", password=PASSWORD)
    here = accounts.create_session(ann.id, user_agent="here")
    there = accounts.create_session(ann.id, user_agent="there")
    _, here_id = accounts.resolve_session(here)
    _, there_id = accounts.resolve_session(there)
    assert {info.user_agent for info in accounts.list_sessions(ann.id)} == {"here", "there"}
    assert not accounts.revoke_session(bo.id, there_id), "not Bo's to revoke"
    assert accounts.revoke_other_sessions(ann.id, here_id) == 1
    assert accounts.resolve_session(there) is None and accounts.resolve_session(here) is not None


def test_changing_a_password_needs_the_current_one_unless_there_is_none(accounts):
    ann = accounts.create_user("ann@example.org", password=PASSWORD)
    with pytest.raises(AccountError, match="current password"):
        accounts.change_password(ann.id, "a new long password", current="wrong")
    accounts.change_password(ann.id, "a new long password", current=PASSWORD)
    assert accounts.authenticate("ann@example.org", "a new long password")

    google = accounts.create_user("bo@example.org", google_sub="g-2", email_verified=True)
    accounts.change_password(google.id, "a first long password", current=None)
    assert accounts.get_user(google.id).has_password


def test_google_can_be_disconnected_only_from_an_account_with_a_password(accounts):
    google_only = accounts.create_user("bo@example.org", google_sub="g-2", email_verified=True)
    with pytest.raises(AccountError, match="Set a password"):
        accounts.unlink_google(google_only.id)
    both = accounts.create_user("ann@example.org", password=PASSWORD, google_sub="g-1")
    assert not accounts.unlink_google(both.id).google_linked


def test_a_google_identity_belongs_to_one_account(accounts):
    ann = accounts.create_user("ann@example.org", password=PASSWORD)
    bo = accounts.create_user("bo@example.org", password=PASSWORD)
    accounts.link_google(ann.id, "g-1")
    assert accounts.get_user(ann.id).email_verified, "Google vouched for the email"
    with pytest.raises(AccountError, match="another account"):
        accounts.link_google(bo.id, "g-1")


def test_a_pending_google_sign_in_is_used_once_and_expires(accounts, clock):
    accounts.save_oauth_state("s1", nonce="n", code_verifier="v", next_path="/", link_user_id=None)
    assert accounts.take_oauth_state("s1").nonce == "n"
    assert accounts.take_oauth_state("s1") is None
    accounts.save_oauth_state("s2", nonce="n", code_verifier="v", next_path="/", link_user_id=None)
    clock.now += timedelta(minutes=11)
    assert accounts.take_oauth_state("s2") is None


def test_registration_follows_the_default_until_an_admin_sets_it(accounts):
    assert accounts.registration_open(default=True) and not accounts.registration_open(default=False)
    accounts.set_registration(False)
    assert not accounts.registration_open(default=True)
    accounts.set_registration(True)
    assert accounts.registration_open(default=False)
