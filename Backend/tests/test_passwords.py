import pytest

from sql_agent import passwords
from sql_agent.passwords import PasswordRejected, check_rules, hash_password, verify_password


def test_a_password_round_trips_and_a_wrong_one_fails():
    stored = hash_password("correct horse battery")
    assert stored.startswith("scrypt$") and "correct" not in stored
    assert verify_password("correct horse battery", stored)
    assert not verify_password("correct horse batterY", stored)


def test_the_same_password_hashes_differently_each_time():
    assert hash_password("correct horse battery") != hash_password("correct horse battery")


def test_a_hash_keeps_its_own_cost_so_raising_the_cost_later_breaks_nothing(monkeypatch):
    old = hash_password("correct horse battery")
    monkeypatch.setattr(passwords, "COST", (2**11, 8, 1))
    assert verify_password("correct horse battery", old)
    assert hash_password("x" * 12).split("$")[1] == str(2**11)


def test_no_stored_hash_or_a_damaged_one_never_verifies():
    assert not verify_password("anything at all", None)
    for damaged in ("", "scrypt$1$2", "bcrypt$1$2$3$4$5", "scrypt$x$8$1$AA==$AA=="):
        assert not verify_password("anything at all", damaged)


@pytest.mark.parametrize("password", ["short", "x" * 11, "x" * 129])
def test_length_is_the_rule(password):
    with pytest.raises(PasswordRejected):
        check_rules(password)
    check_rules("x" * 12)
    check_rules("x" * 128)
