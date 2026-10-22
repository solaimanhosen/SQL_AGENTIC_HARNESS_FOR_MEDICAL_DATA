import pytest

from sql_agent import users
from sql_agent.accounts import AccountStore
from sql_agent.appdb import AppDatabase
from sql_agent.conversations import ConversationStore
from sql_agent.google_login import GoogleIdentity, resolve_account

PASSWORD = "a long enough password"


@pytest.fixture
def path(tmp_path, monkeypatch):
    path = tmp_path / "conversations.db"
    monkeypatch.setenv("SQL_AGENT_CONVERSATIONS_PATH", str(path))
    return path


def typed(*answers):
    answers = list(answers)
    return lambda _prompt: answers.pop(0)


def test_the_first_admin_is_created_with_a_typed_password_and_claims_old_conversations(path, capsys):
    store = ConversationStore(path)
    old, _, _ = store.begin(None)
    store.finish(old, None)
    store._db.execute("UPDATE conversations SET turn_count = 1")
    store.close()

    code = users.main(
        ["create", "admin@gmail.com", "--admin", "--claim-unowned"], prompt=typed(PASSWORD, PASSWORD)
    )
    assert code == 0
    output = capsys.readouterr().out
    assert "admin" in output and "Gave it 1 conversation" in output and PASSWORD not in output

    database = AppDatabase(path)
    accounts = AccountStore(database)
    admin = accounts.authenticate("admin@gmail.com", PASSWORD)
    assert admin.is_admin and admin.email_verified
    assert [s.id for s in ConversationStore(database=database).list(owner=admin.id)] == [old]
    # The address was vouched for here, so the admin may later sign in with Google on it.
    linked = resolve_account(
        accounts, GoogleIdentity("g-1", "admin@gmail.com", "Admin"), link_user_id=None, registration_open=False
    )
    assert linked.id == admin.id


def test_mismatched_or_short_passwords_create_nothing(path, capsys):
    assert users.main(["create", "a@example.org"], prompt=typed(PASSWORD, PASSWORD + "x")) == 1
    assert users.main(["create", "a@example.org"], prompt=typed("short", "short")) == 1
    assert "Not done" in capsys.readouterr().err
    assert AccountStore(AppDatabase(path)).list_users() == []


def test_accounts_are_listed_promoted_disabled_and_reset(path, capsys):
    users.main(["create", "bo@example.org", "--google-only"])
    users.main(["set-role", "bo@example.org", "admin"])
    users.main(["disable", "bo@example.org"])
    users.main(["list"])
    listing = capsys.readouterr().out
    assert "bo@example.org" in listing and "admin" in listing and "disabled" in listing
    assert users.main(["reset-password", "bo@example.org"], prompt=typed(PASSWORD, PASSWORD)) == 0
    assert users.main(["enable", "nobody@example.org"]) == 1


def test_registration_can_be_closed_from_the_command_line(path):
    assert users.main(["registration", "closed"]) == 0
    assert not AccountStore(AppDatabase(path)).registration_open(default=True)
